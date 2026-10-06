"""品項全流程工時成本儀表板（efficiency/index.html）的自動化測試。

用假的 Supabase 回應（不含任何真實資料）測試：
  ‧ 登入：沒登入看到登入框；主管看得到「資料匯入」，檢視者看不到
  ‧ 分頁：超過 1,000 列的 view 會分頁讀完
  ‧ 數字：畫面上的效率指數、損失人時，與本檔用資料庫 sku_eff／plant_month 的規則另外算的結果一致
  ‧ 五頁都畫得出來、沒有 JS 錯誤；暫定月份、物料平衡、工時待處理清單、計算說明
"""
import json, base64, random
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

PAGE = "file:///home/user/packaging-capacity-dashboard/efficiency/index.html"
fails = []

def check(name, cond, extra=""):
    if not cond: fails.append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(extra)))

def b64u(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

JWT = "x." + b64u({"sub": "u-1"}) + ".y"

# ── 假資料 ───────────────────────────────────────────────────
random.seed(7)
MONTHS = ["2025-%02d" % m for m in range(1, 13)] + ["2026-%02d" % m for m in range(1, 11)]
SETTINGS = [
    {"key": "std_base", "value": {"from": "2026-03", "to": "2026-08"}},
    {"key": "gate", "value": {"fg_fill": 95, "head_pct": 95, "missing_days": 0}},
    {"key": "lag_days", "value": {"late": 7}},
    {"key": "balance", "value": {"lo": 0.85, "hi": 1.15, "months": 3}},
]
def gate_row(ym):
    fg = 52.7 if ym == "2026-09" else 0.0 if ym == "2026-10" else 100.0
    miss = 2 if ym == "2026-10" else 0
    head = 88 if ym == "2026-05" else 0 if ym < "2026-03" else 100
    g_mfg, g_pack = fg >= 95, miss == 0
    return {"ym": ym, "fg_fill_pct": fg, "missing_days": miss, "head_pct": head, "pack_batches": 50,
            "labour_invalid": 0, "labour_o_mismatch": 0, "gate_mfg": g_mfg, "gate_pack": g_pack,
            "gate_head": head >= 95, "gate": g_mfg and g_pack, "in_base": "2026-03" <= ym <= "2026-08"}
GATES = [gate_row(m) for m in MONTHS if m >= "2025-10"]

# 120 個品項 × 22 個月 → sku_month 超過 1,000 列，必須分頁
SKUS = ["D0310", "B3011", "E0120"] + ["X%04d" % i for i in range(117)]
SKU_MONTH, STD = [], []
for c in SKUS:
    base = {"mfg": random.uniform(5, 40), "fill": random.uniform(5, 30), "pack": random.uniform(2, 20)}
    if c == "E0120": base["mfg"] = base["fill"] = None          # 只有包裝段的品項
    STD.append({"sku_code": c, "mfg_std": base["mfg"] and round(base["mfg"], 3), "mfg_n": 6 if base["mfg"] else 0,
                "fill_std": base["fill"] and round(base["fill"], 3), "fill_n": 6 if base["fill"] else 0,
                "pack_std": round(base["pack"], 3), "pack_n": 2 if c == "B3011" else 6})
    for ym in MONTHS:
        fg = random.randint(2000, 20000); pb = int(fg * random.uniform(0.8, 1.2))
        f = random.uniform(0.75, 1.3)
        row = {"sku_code": c, "ym": ym, "sku_name": "品項" + c, "fg_used": fg, "n_used": random.randint(1, 6),
               "mfg_h": base["mfg"] and round(base["mfg"] * f * fg / 1000, 3),
               "fill_h": base["fill"] and round(base["fill"] * f * fg / 1000, 3),
               "pack_h": round(base["pack"] * random.uniform(0.8, 1.25) * pb / 1000, 3), "pack_b": pb,
               "per_pot_h": round(random.uniform(1.5, 3), 3), "yield_pct": round(random.uniform(94, 104), 2)}
        if ym >= "2026-10": row["mfg_h"] = row["fill_h"] = None; row["fg_used"] = None   # 10 月製造還沒匯入
        if c == "E0120": row["fg_used"] = None
        SKU_MONTH.append(row)

BATCHES = [{"sku_code": "D0310", "prod_date": "2026-%02d-%02d" % (m, d), "fg": 400, "labour_h": random.uniform(20, 30), "outlier": d == 20}
           for m in range(1, 10) for d in (5, 20)]
LINKED = [
    {"sku_code": "D0310", "mfg_date": "2026-09-30", "pack_h": 12.0, "pack_b": 406, "n_pack": 3, "lag_days": 1, "matched": True,
     "pots": 16, "fg": None, "closed": False, "mfg_h": 15.2, "fill_h": 8.8, "mfg_outlier": False, "labour_bad": 0},
    {"sku_code": "D0310", "mfg_date": "2026-10-01", "pack_h": 10.0, "pack_b": 500, "n_pack": 1, "lag_days": 9, "matched": True,
     "pots": 16, "fg": 520, "closed": True, "mfg_h": 16.0, "fill_h": 9.0, "mfg_outlier": True, "labour_bad": 0},
]
BAL = [{"sku_code": "B3011", "ym": "2026-08", "fg3": 10000, "pb3": 6000, "ratio": 0.6},
       {"sku_code": "X0001", "ym": "2026-08", "fg3": 1000, "pb3": 1300, "ratio": 1.3}]
ISSUES = [{"prod_date": "2026-08-11", "ym": "2026-08", "sku_code": "B3011", "sku_name": "品項B3011", "src_row": 2459, "kind": "invalid", "detail": "製造段缺人數"},
          {"prod_date": "2026-08-27", "ym": "2026-08", "sku_code": "D0310", "sku_name": "品項D0310", "src_row": 2526, "kind": "o_note", "detail": "系統依起訖計算 3480 人·分，Excel O 欄為 3615"}]

# ── 期望值：照資料庫 sku_eff／plant_month 的規則另外算 ──────────
STDM = {s["sku_code"]: s for s in STD}
def expect(ym):
    act = std = loss = 0.0
    for r in SKU_MONTH:
        if r["ym"] != ym: continue
        s = STDM[r["sku_code"]]; a = sd = 0.0
        for h, q, k in ((r["mfg_h"], r["fg_used"], "mfg_std"), (r["fill_h"], r["fg_used"], "fill_std"), (r["pack_h"], r["pack_b"], "pack_std")):
            if h and q and s[k] is not None: a += h; sd += s[k] * q / 1000
        if a: act += a; std += sd; loss += max(0, a - sd)
    return std / act * 100, act, loss

# ── 假的 Supabase ────────────────────────────────────────────
def router(role):
    calls = []
    def page_of(rows, u):
        q = parse_qs(urlparse(u).query)
        off, lim = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["1000"])[0])
        return rows[off:off + min(lim, 1000)]
    def route(r):
        u = r.request.url
        if "vnncuksjvdsxwveomoww" not in u: return r.continue_()
        calls.append(u)
        if "/rest/v1/members" in u: return r.fulfill(json=[{"display_name": "測試帳號", "role": role}])
        if "/rest/v1/settings" in u: return r.fulfill(json=SETTINGS)
        if "/rest/v1/month_gate" in u: return r.fulfill(json=GATES)
        if "/rest/v1/sku_month" in u: return r.fulfill(json=page_of(SKU_MONTH, u))
        if "/rest/v1/sku_std" in u: return r.fulfill(json=page_of(STD, u))
        if "/rest/v1/mfg_batch" in u: return r.fulfill(json=page_of(BATCHES, u))
        if "/rest/v1/batch_link" in u: return r.fulfill(json=LINKED)
        if "/rest/v1/balance_check" in u: return r.fulfill(json=BAL)
        if "/rest/v1/labour_issues" in u: return r.fulfill(json=ISSUES)
        if "/rest/v1/imports" in u: return r.fulfill(json=[{"file_name": "製成率.xlsx", "imported_at": "2026-10-06T08:00:00Z"}])
        return r.fulfill(status=404, body="{}")
    return route, calls

def open_page(b, role="viewer", session=True, width=1280):
    pg = b.new_page(viewport={"width": width, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    route, calls = router(role)
    pg.route("**/*", route)
    if session:
        pg.add_init_script("localStorage.setItem('packing.session', JSON.stringify({access:'%s',refresh:'r',exp:Date.now()+3600e3}))" % JWT)
    pg.goto(PAGE)
    return pg, calls, errs

def tab(pg, p):
    pg.click(f"nav.tabs button[data-p={p}]"); pg.wait_for_timeout(150)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")

    print("── 沒登入 ──")
    pg, calls, errs = open_page(b, session=False)
    pg.wait_for_timeout(300)
    check("顯示登入框", pg.is_visible("#loginBox"))
    check("不顯示儀表板", not pg.is_visible("#app"))
    check("沒有讀任何資料", not any("/rest/v1/" in u for u in calls), calls)

    print("── 檢視者 ──")
    pg, calls, errs = open_page(b, role="viewer")
    pg.wait_for_selector("#app:not(.hidden)")
    check("看不到「資料匯入」", not pg.is_visible("#importLink"))
    check("看得到登出", pg.is_visible("#logout"))
    sm = [u for u in calls if "/rest/v1/sku_month" in u]
    check("sku_month 分頁讀（offset 0、1000、2000）", len(sm) == 3 and "offset=2000" in sm[-1], sm)
    check("第一頁叫「每月總覽」", "每月總覽" in pg.inner_text("nav.tabs"))
    check("預設月份＝最後一個通過門檻的月份（8 月）", pg.input_value("#month") == "2026-08", pg.input_value("#month"))
    opts = pg.eval_on_selector_all("#month option", "o => o.map(x => x.textContent)")
    check("月份選單由新到舊、未過門檻標暫定", opts[0] == "2026 年 10 月（暫定）" and "（暫定）" in opts[1] and "暫定" not in opts[2], opts[:3])
    ei, act, loss = expect("2026-08")
    kp = pg.inner_text("#kpis")
    check("效率指數與資料庫規則一致", f"{ei:.1f}" in kp, (f"{ei:.1f}", kp[:120]))
    check("全流程人時一致", f"{act:,.0f}" in kp, (f"{act:,.0f}", kp))
    check("損失人時一致", f"{loss:,.0f}" in kp, (f"{loss:,.0f}", kp))
    check("資料齊全度 2 / 2", "2 / 2" in kp, kp)
    check("基準期文字由設定產生", "2026/3–8" in pg.inner_text("#lede"), pg.inner_text("#lede"))
    check("頁首顯示最近一次匯入", "2026-10-06" in pg.inner_text("#hdrNote"))
    check("Top 10 有長條", pg.locator("#lossBars .row").count() == 10)

    pg.select_option("#month", "2026-09")
    pg.wait_for_timeout(150)
    check("9 月標暫定（成品數只填 52.7%）", "52.7%" in pg.inner_text("#lede"), pg.inner_text("#lede")[:80])
    ei9, _, _ = expect("2026-09")
    check("9 月效率指數一致", f"{ei9:.1f}" in pg.inner_text("#kpis"))
    pg.select_option("#month", "2026-08")

    pg.fill("#rate", "300"); pg.wait_for_timeout(150)
    check("費率改 300 → 人工成本跟著變", f"{act * 300 / 10000:,.1f} 萬" in pg.inner_text("#kpis"), pg.inner_text("#kpis"))
    pg.fill("#rate", "200")

    print("── 其他頁 ──")
    tab(pg, "p2")
    check("異常地圖有列", pg.locator("table.heat tbody tr").count() > 50)
    check("工段結構有圖", pg.locator("#stack svg path").count() > 0)
    tab(pg, "p3")
    pg.select_option("#sku", "D0310"); pg.wait_for_timeout(150)
    bc = pg.inner_text("#bcards")
    check("批次成本卡：未結案批以包裝瓶數暫代", "未結案" in bc, bc[:200])
    check("批次成本卡：已結案批各用各的分母", "已結案：成品 520 瓶" in bc, bc)
    check("批次成本卡：離群提醒", "離群" in bc)
    check("控制圖有點", pg.locator("#ctrl circle").count() >= 18)
    check("間隔天數：超過 7 天標延遲", "1 延遲" in pg.inner_text("#lag"), pg.inner_text("#lag"))
    check("每鍋人時灰線＝前一年", "2025 年平均" in pg.inner_text("#potSub"))
    pg.select_option("#sku", "E0120"); pg.wait_for_timeout(150)
    check("只有包裝段的品項也畫得出來", "製造" in pg.inner_text("#stage") and "本月無資料" in pg.inner_text("#stage"), pg.inner_text("#stage"))
    tab(pg, "p4")
    check("試算器有結果", "全流程" in pg.inner_text("#calcOut"))
    pg.fill("#calcQtyN", "5000"); pg.wait_for_timeout(150)
    check("數量改 5,000 → 試算更新", "5,000 瓶" in pg.inner_text("#calcOut"))
    pg.select_option("#calcSku", "B3011"); pg.wait_for_timeout(150)
    check("樣本少於 3 個月提醒", "僅供參考" in pg.inner_text("#calcFormula"))
    check("標準成本表不含缺段品項", "E0120" not in pg.inner_text("#stdTbl") and "另有 1 項" in pg.inner_text("#stdTbl"), pg.inner_text("#stdTbl")[-80:])
    check("ROI 有結果", "一年可省金額" in pg.inner_text("#roiOut"))
    tab(pg, "p5")
    li = pg.inner_text("#lights")
    check("門檻兩項通過、人數只提醒", li.count("通過") == 2 and "提醒" in li, li)
    check("物料平衡清單 2 項", pg.locator("#balTbl tbody tr").count() == 2)
    dq = pg.inner_text("#dqTbl")
    check("工時待處理：需修正＋O 欄提醒＋Excel 列號", "需修正" in dq and "O 欄提醒" in dq and "2459" in dq, dq)
    pg.select_option("#month", "2026-09"); pg.wait_for_timeout(150)
    check("成品數未填齊的月份不檢核物料平衡", "暫不檢核" in pg.inner_text("#balTbl") or "暫不檢核" in pg.inner_text("#lights"))

    pg.click("#helpBtn"); pg.wait_for_timeout(100)
    hp = pg.inner_text("#help")
    check("計算說明：午休完整涵蓋才扣", "完整涵蓋 12:00–13:00" in hp)
    check("計算說明：沒填人數的批次排除", "都不列入" in hp)
    check("計算說明：基準期由設定產生", "2026/3–8" in hp)
    pg.click("#helpClose")
    pg.click("#themeBtn"); pg.wait_for_timeout(150)
    check("切換深色沒有錯誤", pg.evaluate("document.documentElement.dataset.theme") == "dark")
    check("沒有 JS 錯誤", not errs, errs[:3])

    print("── 主管、手機寬度 ──")
    pg, calls, errs = open_page(b, role="manager", width=390)
    pg.wait_for_selector("#app:not(.hidden)")
    check("主管看得到「資料匯入」", pg.is_visible("#importLink"))
    for p_ in ("p1", "p2", "p3", "p4", "p5"):
        tab(pg, p_)
        w = pg.evaluate("document.scrollingElement.scrollWidth")
        check(f"手機寬度 {p_} 沒有橫向捲動", w <= 391, w)
    check("沒有 JS 錯誤", not errs, errs[:3])

    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
