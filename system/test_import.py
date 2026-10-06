"""製成率匯入頁（efficiency/import.html）的自動化測試。

用 openpyxl 現場產生一份小 Excel（不含任何真實資料），涵蓋：
  ‧ 日期：Excel 日期、2026/1/2 字串、民國年 115/1/5、無年份 12/30（往後找錨點推年份）、無法辨識
  ‧ 同一天同一料號兩列 → seq 1、2
  ‧ 「成品數(實際)」與「半成品數(實際)」不可抓錯欄
  ‧ 數字料號、專案列、#N/A
  ‧ 工時：時刻、前置、O 欄、R 欄
並以假的 Supabase 回應測試：主管／輸入專員、筆數大減的二次確認、批次失敗的訊息。
"""
import json, base64, datetime as dt, os, tempfile
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

PAGE = "file:///home/user/packaging-capacity-dashboard/efficiency/import.html"
fails = []

def check(name, cond, extra=""):
    if not cond: fails.append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(extra)))

def b64u(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

JWT = "x." + b64u({"sub": "u-1"}) + ".y"

# ── 測試用 Excel ─────────────────────────────────────────────
def make_xlsx(path):
    wb = Workbook()
    ws = wb.active; ws.title = "資料總表"
    ws.append(["日期", "料號", "品項", "鍋數\n(P)", "規格\n(kg)", "平均均數\n(鍋)", "半成品數\n(預估)", "半成品數\n(實際)",
               "半成品重量(KG)\n(實際)", "生產達成率\n(實際)", "生產達成率\n(目標)", "差異統計\n(實際-目標)", "總生產時間(分)",
               "品保取樣數", "不良品數", "成品數\n(實際)", "產品良率\n(成品)", "異常單號", "重工數(kg)", "備註"])
    def row(d, code, name, pots, est, act, fg, note=None):
        r = [d, code, name, pots, 6, None, est, act, None, None, None, None, None, None, 2, fg, None, None, None, note]
        ws.append(r)
    row("2025/12/30", "A1020", "大圓草莓", 32, 11008, 11000, 10950)
    row(dt.datetime(2026, 1, 2), "B2011", "＃1花生", 72, 3369.6, 3399, 3390)
    row(dt.datetime(2026, 1, 2), "B2011", "＃1花生", 10, 400, 398, 395, "同日第二批")
    row("115/1/5", "D0310", "草莓蒟蒻餡", 16, 410, 416, 415)
    row(dt.datetime(2026, 1, 6), "專案", "水蜜桃果醬", 0.6, "#N/A", None, None)
    row(dt.datetime(2026, 1, 7), 111050, "醃漬桔皮", 1, 900, 880, 870)
    row("abc", "C1030", "日期壞掉", 16, 600, 610, 605)

    w = wb.create_sheet("工時")
    w.append(["日期", "料號", "品項", "鍋數\n(P)", "人數", "前置作業", "生產開始時間", "生產結束時間", "生產時間(分)",
              "人數", "前置作業", "生產開始時間", "生產結束時間", "生產時間(分)", "生產時間*人數", "開始", "結束", "總生產時間(分)"])
    w.append([None, None, None, None, "製造", None, None, None, None, "充填"])
    T = dt.time
    # 12/30 沒有年份：往後最近的完整日期是 2026/1/2 → 2025/12/30
    w.append(["12/30", "A1020", "大圓草莓", 32, 5, None, T(7, 0), T(16, 0), 480, 4, T(0, 8), T(7, 30), T(17, 0), 518, 4472, T(7, 0), T(17, 0), 540])
    w.append([dt.datetime(2026, 1, 2), "B2011", "＃1花生", 72, 3, T(0, 40), T(9, 45), T(11, 40), 155, 4, None, T(7, 0), T(19, 10), 700, 3265, T(6, 30), T(19, 10), 700])
    w.append(["1/5", "D0310", "草莓蒟蒻餡", 16, 5, None, T(13, 0), T(16, 58), 238, 4, None, T(13, 40), T(17, 10), 210, 2030, T(13, 0), T(17, 10), 250])
    wb.save(path)

# ── 假的 Supabase ────────────────────────────────────────────
def router(role, current, rpc_fail=False):
    calls = []
    def route(r):
        u = r.request.url
        if "vnncuksjvdsxwveomoww" not in u: return r.continue_()
        if "/rest/v1/members" in u:
            if "user_id=eq." in u: return r.fulfill(json=[{"display_name": "測試主管" if role == "manager" else "測試專員", "role": role}])
            return r.fulfill(json=[{"user_id": "u-1", "display_name": "測試主管"}])
        if "/rest/v1/month_counts" in u: return r.fulfill(json=current)
        if "/rest/v1/rpc/import_months" in u:
            body = json.loads(r.request.post_data); calls.append(body)
            if rpc_fail: return r.fulfill(status=400, json={"message": "有資料列的日期不在這次匯入的月份內，已全部取消"})
            return r.fulfill(json={"import_id": 1, "runs": len(body["p_runs"]), "labour": len(body["p_labour"]), "runs_deleted": 0, "labour_deleted": 0})
        if "/rest/v1/labour_status_by_month" in u: return r.fulfill(json=[{"ym": "2026-01", "ok": 2, "invalid": 0, "empty": 0}])
        if "/rest/v1/imports" in u: return r.fulfill(json=[{"id": 1, "file_name": "t.xlsx", "months": ["2026-01", "2025-12"], "runs_rows": 6, "labour_rows": 3, "imported_by": "u-1", "imported_at": "2026-10-06T08:00:00Z"}])
        return r.fulfill(status=404, body="{}")
    return route, calls

def page(b, role="manager", current=None, rpc_fail=False, session=True):
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    route, calls = router(role, current or [], rpc_fail)
    pg.route("**/*", route)
    if session:
        pg.add_init_script("localStorage.setItem('packing.session', JSON.stringify({access:'%s',refresh:'r',exp:Date.now()+3600e3}))" % JWT)
    pg.goto(PAGE)
    return pg, calls, errs

with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    xl = os.path.join(tmp, "製成率測試.xlsx"); make_xlsx(xl)
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")

    print("── 沒登入 ──")
    pg, _, errs = page(b, session=False)
    pg.wait_for_timeout(300)
    check("顯示登入框", pg.is_visible("#loginBox"))
    check("不顯示匯入區", not pg.is_visible("#app"))

    print("── 輸入專員 ──")
    pg, _, errs = page(b, role="operator")
    pg.wait_for_selector("#app:not(.hidden)")
    check("看不到選擇檔案", not pg.is_visible("#pickCard"))
    check("說明只有主管能匯入", "只有主管帳號" in pg.inner_text("#notManagerMsg"))
    check("看得到匯入紀錄", "t.xlsx" in pg.inner_text("#hist"))

    print("── 主管：解析 ──")
    pg, calls, errs = page(b, current=[{"ym": "2026-01", "runs": 10, "fg_filled": 10, "labour": 2}])
    pg.wait_for_selector("#pickCard:not(.hidden)")
    pg.set_input_files("#file", xl)
    pg.wait_for_selector("#diffCard:not(.hidden)")
    info = pg.inner_text("#parseInfo")
    check("資料總表 6 列（壞日期那列不算）", "資料總表 6 列" in info, info)
    check("工時 3 列", "工時 3 列" in info, info)
    check("列出日期無法辨識的列", "C1030" in pg.inner_text("#dbOnly"), pg.inner_text("#dbOnly"))
    check("2026-01 筆數大減標紅", pg.locator("tr.drop-row").count() == 1)
    check("未確認前不能匯入", pg.is_disabled("#go"))
    pg.check("#dropOk")
    check("確認後可以匯入", not pg.is_disabled("#go"))

    print("── 主管：送出內容 ──")
    pg.click("#go"); pg.wait_for_selector("#resultCard:not(.hidden)")
    check("一批送完（2 個月）", len(calls) == 1 and sorted(calls[0]["p_months"]) == ["2025-12", "2026-01"], [c["p_months"] for c in calls])
    runs = {(r["sku_code"], r["prod_date"], r["seq"]): r for r in calls[0]["p_runs"]}
    lab = {(r["sku_code"], r["prod_date"]): r for r in calls[0]["p_labour"]}
    check("字串日期 2025/12/30", ("A1020", "2025-12-30", 1) in runs)
    check("民國年 115/1/5 → 2026-01-05", ("D0310", "2026-01-05", 1) in runs)
    check("同日同料號第二列 seq=2", ("B2011", "2026-01-02", 2) in runs)
    check("數字料號轉成文字", ("111050", "2026-01-07", 1) in runs)
    check("成品數抓第 P 欄，不是半成品數", runs[("A1020", "2025-12-30", 1)]["fg_act"] == 10950, runs[("A1020", "2025-12-30", 1)])
    check("半成品數（實際）", runs[("A1020", "2025-12-30", 1)]["semi_act"] == 11000)
    check("#N/A 變成空值", runs[("專案", "2026-01-06", 1)]["semi_est"] is None)
    check("無年份 12/30 往後找錨點 → 2025-12-30", ("A1020", "2025-12-30") in lab, list(lab))
    check("無年份 1/5 → 2026-01-05", ("D0310", "2026-01-05") in lab, list(lab))
    a = lab[("A1020", "2025-12-30")]
    check("時刻轉 HH:MM", a["mfg_start"] == "07:00" and a["fill_end"] == "17:00", a)
    check("前置 00:08 → 8 分", a["fill_prep_min"] == 8, a)
    check("O 欄與 R 欄", a["listed_person_min"] == 4472 and a["listed_total_min"] == 540, a)
    check("B2011 前置 00:40 → 40 分", lab[("B2011", "2026-01-02")]["mfg_prep_min"] == 40)
    check("結果顯示", "已匯入 2 個月份" in pg.inner_text("#resultSub"), pg.inner_text("#resultSub"))
    check("步驟停在 ④", "on" in pg.get_attribute("#st4", "class"))
    check("沒有 JS 錯誤", not errs, errs[:3])

    print("── 主管：資料庫拒絕 ──")
    pg, calls, errs = page(b, rpc_fail=True)
    pg.wait_for_selector("#pickCard:not(.hidden)")
    pg.set_input_files("#file", xl); pg.wait_for_selector("#diffCard:not(.hidden)")
    pg.click("#selRecent")
    check("只選最近 2 個月", "2 個月份" in pg.inner_text("#goNote"), pg.inner_text("#goNote"))
    pg.click("#go"); pg.wait_for_timeout(400)
    e = pg.inner_text("#importErr")
    check("說明這一批已取消、資料庫維持原樣", "已全部取消" in e and "維持原樣" in e, e)
    check("可以再按一次", not pg.is_disabled("#go"))
    check("沒有 JS 錯誤", not errs, errs[:3])

    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
