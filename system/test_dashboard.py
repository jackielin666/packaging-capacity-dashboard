"""儀表板讀取資料庫的流程測試。攔截網路請求模擬後端，不需要真的連線。"""
import json, base64
from playwright.sync_api import sync_playwright

PAGE = "file:///home/user/packaging-capacity-dashboard/index.html"

def b64u(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
JWT = "x." + b64u({"sub": "11111111-2222-3333-4444-555555555555"}) + ".y"

# 資料庫裡的資料刻意比內建快照多一天（2026-09-15），才看得出有沒有換成最新的
LIVE = []
for d in range(1, 16):
    LIVE.append({"sku_code": "D0310", "prod_date": "2026-09-%02d" % d,
                 "hours": 1.5, "bottles": 380 + d})
for d in range(1, 16):
    LIVE.append({"sku_code": "B2011", "prod_date": "2026-09-%02d" % d,
                 "hours": 2.5, "bottles": 2000 + d})

calls = {"auth": 0, "batches": 0}

def route(r):
    u, m = r.request.url, r.request.method
    if "fonts.g" in u:
        return r.abort()
    if "/auth/v1/token" in u:
        calls["auth"] += 1
        body = json.loads(r.request.post_data or "{}")
        if "grant_type=password" in u and body.get("password") != "good":
            return r.fulfill(status=400, content_type="application/json",
                             body=json.dumps({"error_description": "Invalid login credentials"}))
        return r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"access_token": JWT, "refresh_token": "rt", "expires_in": 3600}))
    if "/rest/v1/members" in u:
        return r.fulfill(status=200, content_type="application/json",
                         body=json.dumps([{"display_name": "測試主管", "role": "manager"}]))
    if "/rest/v1/batches" in u:
        calls["batches"] += 1
        return r.fulfill(status=200, content_type="application/json", body=json.dumps(LIVE))
    return r.continue_()

fails = []
def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(extra)))
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")

    # ── 情境一：沒登入過的人（例如業務、生管）──────────────
    ctx = b.new_context(viewport={"width": 1280, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/*", route)
    pg.goto(PAGE)
    pg.wait_for_timeout(1500)

    print("\n── 沒登入：維持公開可看 ──")
    check("不強迫登入，直接看得到內容", pg.is_visible("#srcNow"))
    check("登入視窗預設關閉", pg.locator("#lg[hidden]").count() == 1)
    src = pg.inner_text("#srcNow")
    check("標明是內建快照及其日期", "內建快照" in src and "2026-08" in src, src)
    check("沒有偷偷去打資料庫", calls["batches"] == 0, calls)
    kpi = pg.inner_text(".kpis")
    check("KPI 有數字", "214.0" in kpi or "2,755" in kpi, kpi[:80])
    check("KPI 標出產能單位", "單位/hr" in kpi, kpi[:160])
    check("全廠那格叫整體產能", "整體產能" in kpi, kpi[:160])
    ov = pg.inner_text("#ovBody") if pg.locator("#ovBody").count() else pg.inner_text("table")
    check("品項總覽欄名改為平常水準", "平常水準" in pg.inner_text("section"), "")

    tabs = pg.locator(".topbar .tabs a")
    check("頂欄有兩個分頁", tabs.count() == 2, tabs.count())
    check("目前在儀表板且標示為選中",
          "on" in (tabs.nth(1).get_attribute("class") or ""), tabs.nth(1).get_attribute("class"))
    check("另一個連到資料輸入", tabs.nth(0).get_attribute("href") == "entry.html",
          tabs.nth(0).get_attribute("href"))
    check("系統名稱與輸入頁一致", pg.inner_text(".topbar .t") == "包裝產能系統",
          pg.inner_text(".topbar .t"))
    bar = pg.evaluate("getComputedStyle(document.querySelector('.topbar')).backgroundColor")
    check("頂欄底色與輸入頁相同（rgb(10,106,93)）", bar == "rgb(10, 106, 93)", bar)

    print("\n── 按「讀取最新資料」會要求登入 ──")
    pg.click("#liveBtn")
    pg.wait_for_timeout(400)
    check("跳出登入視窗", pg.is_visible("#lgForm"))

    pg.fill("#lgAcc", "admin000"); pg.fill("#lgPw", "wrong")
    pg.click("#lgBtn"); pg.wait_for_timeout(600)
    check("密碼錯誤有明確訊息", "帳號或密碼不對" in pg.inner_text("#lgErr"),
          pg.inner_text("#lgErr"))
    check("失敗時不關視窗", pg.is_visible("#lgForm"))

    print("\n── 登入成功後換成最新資料 ──")
    pg.fill("#lgPw", "good")
    pg.click("#lgBtn"); pg.wait_for_timeout(1500)
    check("視窗關閉", pg.locator("#lg[hidden]").count() == 1)
    src = pg.inner_text("#srcNow")
    check("來源改為資料庫並標出最後日期", "資料庫最新資料" in src and "2026-09-15" in src, src)
    check("確實去讀了資料庫", calls["batches"] >= 1, calls)
    check("已不提供 Excel 上傳", pg.locator("#pickFile").count() == 0)
    check("已移除起始年度選單", pg.locator("#startYear").count() == 0)
    kpi = pg.inner_text(".kpis")
    check("KPI 換成資料庫的數字", "5,880" in kpi or "60" in kpi, kpi[:120])

    print("\n── 可以切回內建快照 ──")
    pg.click("#resetFile"); pg.wait_for_timeout(800)
    check("來源切回快照", "內建快照" in pg.inner_text("#srcNow"), pg.inner_text("#srcNow"))
    check("來源說明改為由輸入系統維護", "輸入系統" in pg.inner_text(".privacy"),
          pg.inner_text(".privacy"))
    ctx.close()

    # ── 情境二：在輸入頁登入過的人，打開儀表板就是最新的 ──
    print("\n── 已登入過：自動帶出最新資料 ──")
    calls["batches"] = 0
    ctx2 = b.new_context(viewport={"width": 1280, "height": 1000})
    ctx2.add_init_script(("""
      localStorage.setItem('packing.session', JSON.stringify(
        {access:'%s', refresh:'rt', exp: Date.now() + 3600000}));
    """ % JWT))
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.route("**/*", route)
    pg2.goto(PAGE)
    pg2.wait_for_timeout(2000)
    src = pg2.inner_text("#srcNow")
    check("開頁即自動換成資料庫資料", "資料庫最新資料" in src, src)
    pg2.wait_for_timeout(600)
    check("頂欄顯示登入者與角色", "測試主管" in pg2.inner_text("#dashWho")
          and "主管" in pg2.inner_text("#dashWho"), pg2.inner_text("#dashWho"))
    check("不需要再按任何按鈕", calls["batches"] >= 1, calls)
    pg2.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/"
                        "fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/dash_live.png",
                   clip={"x": 0, "y": 0, "width": 1280, "height": 620})
    ctx2.close()

    print("\n── 月報 ──")
    ctx3 = b.new_context(viewport={"width": 1280, "height": 1000})
    pg3 = ctx3.new_page()
    pg3.on("pageerror", lambda e: errs.append(str(e)))
    pg3.route("**/*", route)
    pg3.goto(PAGE)
    pg3.wait_for_timeout(1500)

    opts = pg3.locator("#repMonth option").count()
    check("月份選單有內容", opts >= 11, opts)
    first = pg3.locator("#repMonth option").first.inner_text()
    check("最新的月份排最前面", "2026 年 8 月" in first, first)

    pg3.select_option("#repMonth", "2026-07")
    pg3.click("#repBtn")
    pg3.wait_for_timeout(600)
    check("月報預覽打開", pg3.is_visible("#repBody"))
    body = pg3.inner_text("#repBody")
    check("標題是所選月份", "2026 年 7 月" in body, body[:60])
    check("有當月概況", "當月概況" in body)
    check("有與上月比較", "箭頭為與" in body and "2026 年 6 月" in body, body[:400])
    check("有品項表", "當月產出品項" in body)
    check("有需要說明的批次", "需要說明的批次" in body)
    import re as _re
    check("情況欄標出差距百分比",
          _re.search(r"(低於|高於)平常 \d+%", body) is not None,
          [l for l in body.split("\n") if "於平常" in l][:3])
    check("有吃工時的品項段落", "吃工時但產量不高" in body)
    check("標明責任歸屬", "不是包裝作業的問題" in body or "本月沒有工時佔比" in body)
    check("標明資料來源", "資料來源" in body, body[:200])

    rows = pg3.locator("#repBody .rtab").first.locator("tbody tr").count()
    check("品項表有資料", rows > 0, rows)

    # 數字要跟資料庫對得起來：七月 151 批
    check("批次數與資料一致", "151" in body, [l for l in body.split("\n") if "批次" in l][:2])

    check("列印按鈕存在", pg3.is_visible("#repPrint"))
    heads = pg3.inner_text("#repBody .rtab")
    check("月報表頭標出產能單位", "單位/hr" in heads, heads[:200])
    check("月報平常水準說明是中位數", "中位數" in body, body[:900])
    check("有資料完整性段落", "資料完整性" in body, body[-300:])
    check("未登入時誠實說明無法檢核", "未登入" in pg3.inner_text("#repChk"),
          pg3.inner_text("#repChk"))
    check("沒有跑出多餘的引號或加號", "' + '" not in body and "+ '" not in body,
          [l for l in body.split("\n") if "+ '" in l][:2])
    kpitxt = pg3.inner_text("#repBody .rep-kpi")
    check("KPI 的比較文字不會斷行", "對比上\n月" not in kpitxt, kpitxt[:120])
    pg3.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/"
                        "fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/report.png",
                   full_page=True)
    pg3.keyboard.press("Escape")
    pg3.wait_for_timeout(300)
    check("Esc 可以關閉", pg3.locator("#rep[hidden]").count() == 1)
    ctx3.close()

    print("\n── console ──")
    real = [e for e in errs if "ERR_FAILED" not in e]
    check("沒有 JS 錯誤", not real, real[:2])
    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
