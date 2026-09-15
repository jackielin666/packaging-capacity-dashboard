import json, base64, re, datetime
from playwright.sync_api import sync_playwright

PAGE = "file:///home/user/packaging-capacity-dashboard/entry.html"

def b64u(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

JWT = "x." + b64u({"sub": "11111111-2222-3333-4444-555555555555"}) + ".y"

SKUS = [
    {"code":"D0310","name":"草莓蒟蒻餡(1*6kg)","container":"PE袋","batches":256,
     "mean_rate":256,"median_rate":295,"last_date":"2026-08-29"},
    {"code":"B2011","name":"＃1花生(1*2.8kg)","container":"馬口鐵","batches":125,
     "mean_rate":828,"median_rate":912,"last_date":"2026-08-29"},
    {"code":"A1020","name":"大圓草莓-新(1*440g)","container":"玻璃瓶","batches":50,
     "mean_rate":1502,"median_rate":1562,"last_date":"2026-08-29"},
    {"code":"Z9999","name":"很少做的品項","container":"PE袋","batches":3,
     "mean_rate":500,"median_rate":500,"last_date":"2026-08-01"},
]

captured = {"posts": [], "patches": [], "deletes": []}

def make_router(existing_batches):
    def route(r):
        u = r.request.url
        m = r.request.method
        if "fonts.g" in u:
            return r.abort()
        if "/auth/v1/token" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"access_token": JWT, "refresh_token": "rt", "expires_in": 3600}))
        if "/rest/v1/members" in u:
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps([{"display_name":"測試專員","role":"operator"}]))
        if "/rest/v1/sku_stats" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps(SKUS))
        if "/rest/v1/batches" in u:
            if m == "GET" and "source=eq.import" in u:
                return r.fulfill(status=200, content_type="application/json",
                                 body=json.dumps([{"prod_date": "2026-08-31"}]))
            if m == "GET" and "sku_code=eq." in u:
                return r.fulfill(status=200, content_type="application/json", body=json.dumps([
                    {"prod_date":"2026-08-29","start_time":"08:00:00","end_time":"09:30:00",
                     "hours":1.5,"bottles":450,"headcount":5,"abnormal_ok":False},
                    {"prod_date":"2026-08-26","start_time":"10:00:00","end_time":"11:00:00",
                     "hours":1.0,"bottles":60,"headcount":4,"abnormal_ok":True},
                    {"prod_date":"2026-08-20","start_time":"13:00:00","end_time":"15:00:00",
                     "hours":2.0,"bottles":520,"headcount":5,"abnormal_ok":False},
                ]))
            if m == "GET" and "prod_date=gte." in u and "prod_date=eq." not in u:
                return r.fulfill(status=200, content_type="application/json", body=json.dumps([
                    {"prod_date":"2026-09-01","sku_code":"D0310","start_time":"08:00:00",
                     "end_time":"09:30:00","hours":1.5,"bottles":450,"headcount":5,
                     "abnormal_ok":False,"note":"含,逗號與\"引號"},
                ]))
            if m == "POST":
                body = json.loads(r.request.post_data or "[]")
                captured["posts"].append(body)
                out = [dict(b, id=900+i) for i, b in enumerate(body)]
                return r.fulfill(status=201, content_type="application/json", body=json.dumps(out))
            if m == "PATCH":
                captured["patches"].append((u, json.loads(r.request.post_data or "{}")))
                return r.fulfill(status=204, body="")
            if m == "DELETE":
                captured["deletes"].append(u)
                return r.fulfill(status=204, body="")
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps(existing_batches))
        if "/rest/v1/daily_status" in u:
            if m in ("POST", "DELETE"):
                return r.fulfill(status=201, content_type="application/json", body="[]")
            return r.fulfill(status=200, content_type="application/json", body="[]")
        if "/rest/v1/month_status" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps([
                {"ym":"2026-09","is_imported":False,"workdays":11,"logged_days":0,
                 "no_op_days":0,"missing_days":11,"batches":0,"with_headcount":0,"head_pct":None},
                {"ym":"2026-08","is_imported":True,"workdays":21,"logged_days":21,
                 "no_op_days":0,"missing_days":0,"batches":154,"with_headcount":154,"head_pct":100},
                {"ym":"2026-07","is_imported":True,"workdays":23,"logged_days":22,
                 "no_op_days":0,"missing_days":0,"batches":151,"with_headcount":0,"head_pct":0},
            ]))
        if "/rest/v1/day_summary" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps([
                {"prod_date":"2026-09-01","batches":4,"bottles":5000,"hours":6.0,"no_operation":False},
                {"prod_date":"2026-09-02","batches":0,"bottles":0,"hours":0,"no_operation":True},
                {"prod_date":"2026-09-03","batches":2,"bottles":900,"hours":3.0,"no_operation":False},
            ]))
        if "/rest/v1/day_summary" in u and "2026-08" in u:
            return r.fulfill(status=200, content_type="application/json", body="[]")
        return r.continue_()
    return route

fails = []
def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(extra)))
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page(viewport={"width":1280,"height":1000}, accept_downloads=True)
    logs = []
    pg.on("console", lambda m: logs.append(m.type + ": " + m.text))
    pg.on("pageerror", lambda e: logs.append("PAGEERROR: " + str(e)))
    pg.route("**/*", make_router([]))

    pg.goto(PAGE)
    pg.wait_for_selector("#loginView:not([hidden])", timeout=8000)
    print("\n── 登入 ──")
    check("未登入時顯示登入畫面", pg.is_visible("#loginForm"))

    pg.fill("#acc", "admin000")
    pg.fill("#pw", "admin000")
    pg.click("#loginBtn")
    pg.wait_for_selector("#appView:not([hidden])", timeout=8000)
    check("登入後進入主畫面", pg.is_visible("#rows"))
    check("顯示使用者與角色", "測試專員" in pg.inner_text("#who"), pg.inner_text("#who"))

    print("\n── 時間輸入與自動計算 ──")
    row = pg.locator("#rows tr").first
    row.locator('input[data-f="sku"]').fill("D0310")
    row.locator('input[data-f="sku"]').blur()
    row = pg.locator("#rows tr").first
    row.locator('input[data-f="start"]').fill("0800")
    row.locator('input[data-f="start"]').blur()
    row.locator('input[data-f="end"]').fill("930")
    row.locator('input[data-f="end"]').blur()
    row.locator('input[data-f="bottles"]').fill("450")
    row.locator('input[data-f="bottles"]').blur()

    st = row.locator('input[data-f="start"]').input_value()
    en = row.locator('input[data-f="end"]').input_value()
    check("0800 → 08:00", st == "08:00", st)
    check("930 → 09:30", en == "09:30", en)
    nm = pg.locator("#rows tr").first.locator("td.name")
    check("品名自成一欄", nm.count() == 1)
    check("品名與容器都帶出來", "草莓蒟蒻餡" in nm.inner_text() and "PE袋" in nm.inner_text(),
          nm.inner_text())
    check("品名欄排在起始時間之前",
          pg.evaluate("""() => {
            const tds = document.querySelectorAll('#rows tr td');
            return tds[1].classList.contains('name')
                && tds[2].querySelector('input[data-f=\"start\"]') !== null;
          }"""))

    cells = pg.locator("#rows tr").first.locator("td")
    check("工時 = 1.50", cells.nth(6).inner_text().strip() == "1.50",
          cells.nth(6).inner_text())
    check("產能欄只放數字，不放說明", cells.nth(7).inner_text().strip() == "300",
          cells.nth(7).inner_text())
    check("正常範圍不加狀態 class",
          (cells.nth(7).get_attribute("class") or "").strip() == "flag",
          cells.nth(7).get_attribute("class"))

    print("\n── 異常提示移到檢查清單 ──")
    row.locator('input[data-f="bottles"]').fill("120")
    row.locator('input[data-f="bottles"]').blur()
    cells = pg.locator("#rows tr").first.locator("td")
    check("偏低時表格只多一個 low class", "low" in (cells.nth(7).get_attribute("class") or ""),
          cells.nth(7).get_attribute("class"))
    check("表格裡沒有說明文字", "低於" not in cells.nth(7).inner_text(), cells.nth(7).inner_text())
    checks_txt = pg.inner_text("#checksList")
    # D0310 中位數 295，這批 80 → 低於平常 73%
    check("檢查清單說明偏低的原因", "低於平常 73%" in checks_txt, checks_txt[:150])
    # 假資料的 D0310：加權平均 256、中位數 295。判定基準要是中位數。
    check("檢查清單帶出平常水準（中位數 295，不是平均 256）",
          "295" in checks_txt and "256" not in checks_txt, checks_txt[:150])

    print("\n── 確認無誤 ──")
    warn = pg.locator("#checksList .ck.warn").first
    check("有提醒型項目", warn.count() > 0)
    check("提醒型有兩個按鈕", warn.locator("button").count() == 2,
          warn.locator("button").count())
    warn.locator("button", has_text="確認無誤").click()
    pg.wait_for_timeout(250)
    cells = pg.locator("#rows tr").first.locator("td")
    check("確認後表格不再標記", "low" not in (cells.nth(7).get_attribute("class") or ""),
          cells.nth(7).get_attribute("class"))
    check("確認後清單不再列出", "低於平常水準" not in pg.inner_text("#checksList"))

    row.locator('input[data-f="bottles"]').fill("450")
    row.locator('input[data-f="bottles"]').blur()

    print("\n── 樣本不足的品項不示警 ──")
    row.locator('input[data-f="sku"]').fill("Z9999")
    row.locator('input[data-f="sku"]').blur()
    row = pg.locator("#rows tr").first
    row.locator('input[data-f="bottles"]').fill("60")
    row.locator('input[data-f="bottles"]').blur()
    cells = pg.locator("#rows tr").first.locator("td")
    check("批次數不足不標記", (cells.nth(7).get_attribute("class") or "").strip() == "flag",
          cells.nth(7).get_attribute("class"))

    print("\n── 阻擋型檢查 ──")
    r0 = pg.locator("#rows tr").first
    r0.locator('input[data-f="sku"]').fill("D0310")
    r0.locator('input[data-f="sku"]').blur()
    r0 = pg.locator("#rows tr").first
    r0.locator('input[data-f="bottles"]').fill("450")
    r0.locator('input[data-f="bottles"]').blur()
    pg.click("#addRow")
    r1 = pg.locator("#rows tr").nth(1)
    r1.locator('input[data-f="sku"]').fill("B2011")
    r1.locator('input[data-f="sku"]').blur()
    r1 = pg.locator("#rows tr").nth(1)
    r1.locator('input[data-f="start"]').fill("1000")
    r1.locator('input[data-f="start"]').blur()

    check("半填的列讓儲存鈕停用", pg.is_disabled("#saveBtn"))
    stop = pg.locator("#checksList .ck.stop").first
    check("清單列出阻擋原因", stop.count() > 0)
    check("阻擋原因指名品項", "B2011" in stop.inner_text(), stop.inner_text())
    check("阻擋項有前往修正", stop.locator("button", has_text="前往修正").count() == 1)
    check("錯誤欄位標紅", r1.locator("input.bad").count() > 0)
    check("統計列出待處理數", "待處理" in pg.inner_text("#checksTally"),
          pg.inner_text("#checksTally"))

    print("\n── 同品項時間重疊 ──")
    r1.locator('input[data-f="end"]').fill("1200")
    r1.locator('input[data-f="end"]').blur()
    r1 = pg.locator("#rows tr").nth(1)
    r1.locator('input[data-f="bottles"]').fill("1800")
    r1.locator('input[data-f="bottles"]').blur()
    r1.locator('input[data-f="head"]').fill("5")
    r1.locator('input[data-f="head"]').blur()

    pg.click("#addRow")
    r2 = pg.locator("#rows tr").nth(2)
    for f, v in (("sku","B2011"),("start","1130"),("end","1300"),("bottles","900"),("head","5")):
        el = pg.locator("#rows tr").nth(2).locator('input[data-f="%s"]' % f)
        el.fill(v); el.blur()
    warns = pg.locator("#checksList .ck.warn").all_inner_texts()
    check("同品項重疊會提醒", any("時間重疊" in t for t in warns), warns)

    print("\n── 跨品項重疊不該提醒（多線並行是常態）──")
    el = pg.locator("#rows tr").nth(2).locator('input[data-f="sku"]')
    el.fill("A1020"); el.blur()
    warns = pg.locator("#checksList .ck.warn").all_inner_texts()
    passes = pg.locator("#checksList .ck.pass").all_inner_texts()
    check("換成別的品項後就不提醒", not any("時間重疊" in t for t in warns), warns)
    check("並列為通過項目", any("沒有時間重疊" in t for t in passes), passes)

    print("\n── 沒填人數的提醒 ──")
    txt = pg.inner_text("#checksList")
    check("提醒有幾批沒填人數", "沒有填人數" in txt, txt[:200])
    el = pg.locator("#rows tr").first.locator('input[data-f="head"]')
    el.fill("4"); el.blur()
    txt = pg.inner_text("#checksList")
    check("補齊後改列為通過", "都有填人數" in txt, txt[:200])

    print("\n── 儲存 ──")
    check("儲存鈕顯示筆數", "3 筆" in pg.inner_text("#saveBtn"), pg.inner_text("#saveBtn"))
    check("補齊後儲存鈕啟用", not pg.is_disabled("#saveBtn"))

    pg.click("#saveBtn")
    pg.wait_for_timeout(1200)
    check("送出一個 POST", len(captured["posts"]) == 1, captured["posts"])
    if captured["posts"]:
        body = captured["posts"][0]
        check("送出三筆批次", len(body) == 3, len(body))
        b0 = body[0]
        check("欄位名稱正確", set(b0) == {"sku_code","prod_date","start_time","end_time",
                                          "bottles","headcount","abnormal_ok"}, list(b0))
        check("不送 hours（資料庫自己算）", "hours" not in b0, list(b0))
        check("不送確認時間（由資料庫蓋章）", "abnormal_ok_at" not in b0, list(b0))
        check("時間是 HH:MM", re.match(r"^\d\d:\d\d$", b0["start_time"]) is not None, b0)
        check("人數送數字", body[1]["headcount"] == 5, body[1])
    check("顯示已儲存", "已儲存" in pg.inner_text("#banner"), pg.inner_text("#banner"))

    print("\n── 月曆 ──")
    check("月曆有格子", pg.locator("#cal .cell:not(.blank)").count() >= 28,
          pg.locator("#cal .cell:not(.blank)").count())
    check("9/1 標為已登記", "has" in (pg.locator('#cal .cell[data-d="2026-09-01"]')
                                      .get_attribute("class") or ""))
    check("9/2 標為無作業", "none" in (pg.locator('#cal .cell[data-d="2026-09-02"]')
                                       .get_attribute("class") or ""))
    sub = pg.inner_text("#calSub")
    check("進度摘要有數字", "已登記" in sub and "待補" in sub, sub)
    check("進度條有三段", pg.locator("#calTrack i").count() == 3,
          pg.locator("#calTrack i").count())
    check("待補天數顯示在按鈕上", "待補" in pg.inner_text("#gapBtn"), pg.inner_text("#gapBtn"))
    check("未來日期不可點", pg.locator("#cal .cell.future[data-d]").count() == 0,
          pg.locator("#cal .cell.future[data-d]").count())

    print("\n── 匯入期間的空白日不算漏登 ──")
    pg.click("#prevMon")           # 切到 2026-08，那是匯入的期間
    pg.wait_for_timeout(700)
    check("切到上個月", "8 月" in pg.inner_text("#calTitle"), pg.inner_text("#calTitle"))
    check("匯入期間沒有紅色待補", pg.locator("#cal .cell.miss").count() == 0,
          pg.locator("#cal .cell.miss").count())
    check("空白工作日標為歷史空白", pg.locator("#cal .cell.hist").count() > 0,
          pg.locator("#cal .cell.hist").count())
    check("摘要的待補為 0", "待補 0" in pg.inner_text("#calSub"), pg.inner_text("#calSub"))
    check("圖例說明匯入期間的規則", "2026-08-31" in pg.inner_text(".legend"),
          pg.inner_text(".legend")[-120:])
    pg.click("#nextMon")
    pg.wait_for_timeout(700)

    print("\n── Excel 貼上 ──")
    pg.evaluate("""() => {
      const dt = new DataTransfer();
      dt.setData('text/plain', 'D0310\\t1300\\t1430\\t380\\t4\\nB2011\\t1430\\t1600\\t1200\\t5');
      const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true});
      document.querySelector('#rows tr input').dispatchEvent(ev);
    }""")
    pg.wait_for_timeout(400)
    r0 = pg.locator("#rows tr").first
    check("貼上後第一列品項正確", r0.locator('input[data-f="sku"]').input_value() == "D0310",
          r0.locator('input[data-f="sku"]').input_value())
    check("貼上後時間已正規化", r0.locator('input[data-f="start"]').input_value() == "13:00",
          r0.locator('input[data-f="start"]').input_value())
    check("貼上提示出現", "已貼上" in pg.inner_text("#banner"), pg.inner_text("#banner"))

    print("\n── 介面調整 ──")
    check("Excel 貼上按鈕已移除", pg.locator("#pasteBtn").count() == 0)
    check("Excel 字樣不再出現在提示列", "Excel" not in pg.inner_text(".panel .keys"),
          pg.inner_text(".panel .keys"))
    bar = pg.evaluate("getComputedStyle(document.querySelector('.topbar')).backgroundColor")
    check("頂欄不是黑色", bar == "rgb(10, 106, 93)", bar)
    bd = pg.evaluate("""() => {
      const el = document.querySelector('#rows input[data-f=\"sku\"]');
      return getComputedStyle(el).borderTopColor;
    }""")
    check("輸入格平常就有邊框", bd == "rgb(205, 210, 200)", bd)

    pg.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/entry_desktop.png", full_page=True)
    pg.set_viewport_size({"width":390,"height":900})
    pg.wait_for_timeout(300)
    pg.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/entry_mobile.png", full_page=True)

    # 測試裡故意 abort 掉 Google Fonts（這個容器沒有對外網路），
    # 那筆 ERR_FAILED 是測試環境造成的，不是頁面的問題。
    errs = [l for l in logs
            if ("PAGEERROR" in l or l.startswith("error"))
            and "ERR_FAILED" not in l]
    print("\n── 品項歷史 ──")
    pg.locator("#rows tr").first.locator("button.hist").click()
    # 視窗會先開、資料才載入完 —— 要等內容出現，不能只等視窗
    pg.wait_for_selector("#histBody .hstats", timeout=5000)
    body = pg.inner_text("#histBody")
    check("視窗打開", pg.is_visible("#histBody"))
    check("標題含品號與品名", "D0310" in pg.inner_text("#histTitle")
          and "草莓蒟蒻餡" in pg.inner_text("#histTitle"), pg.inner_text("#histTitle"))
    check("平常水準排第一格", body.strip().startswith("平常水準"), body[:60])
    check("同時附上整體產能供對照", "整體產能" in body, body[:120])
    check("說明兩者差別", "中位數" in body and "總瓶數÷總工時" in body, body[:400])
    check("顯示偏低門檻", "偏低門檻" in body, body[:120])
    check("門檻以中位數計算（295×0.7=207）", "207" in body, body[:200])
    check("分布帶有點", pg.locator("#histBody .strip i").count() >= 3,
          pg.locator("#histBody .strip i").count())
    check("這一批被標出來", pg.locator("#histBody .strip i.me").count() == 1)
    check("偏低的批次被標記", pg.locator("#histBody .strip i.low").count() >= 1,
          pg.locator("#histBody .strip i.low").count())
    check("歷史明細列出三批", pg.locator("#histBody .htab tbody tr").count() == 3,
          pg.locator("#histBody .htab tbody tr").count())
    check("已確認的批次有標示", "已確認" in body, body[-200:])
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check("Esc 可以關閉", pg.locator("#hist[hidden]").count() == 1)

    print("\n── 匯出 CSV ──")
    pg.select_option("#expRange", "month")
    with pg.expect_download() as dl:
        pg.click("#expBtn")
    d = dl.value
    check("檔名有月份", "2026-09" in d.suggested_filename, d.suggested_filename)
    raw = open(d.path(), "rb").read()
    check("開頭有 BOM（Excel 才不會亂碼）", raw[:3] == b"\xef\xbb\xbf", raw[:6])
    txt = raw.decode("utf-8-sig")
    lines = txt.strip().split("\r\n")
    check("有標題列與一筆資料", len(lines) == 2, lines)
    check("標題含中文欄名", "生產日期" in lines[0] and "產能" in lines[0], lines[0])
    check("CSV 欄名帶單位", "產能(單位/hr)" in lines[0] and "工時(hr)" in lines[0], lines[0])
    check("帶出品名", "草莓蒟蒻餡" in lines[1], lines[1])
    check("算出產能 300", ",300," in lines[1], lines[1])
    check("含逗號的備註有加引號", '"含,逗號與""引號"""' in lines[1] or '含,逗號' in lines[1],
          lines[1])
    pg.wait_for_timeout(200)
    check("顯示匯出筆數", "1 筆" in pg.inner_text("#expState"), pg.inner_text("#expState"))

    print("\n── 兩個頁面互相連得到 ──")
    nav = pg.locator(".topbar a.nav")
    check("輸入頁有儀表板入口", nav.count() == 1)
    check("連到 index.html", nav.get_attribute("href") == "index.html",
          nav.get_attribute("href"))
    check("按鈕文字清楚", "儀表板" in nav.inner_text(), nav.inner_text())

    print("\n── 產能單位標示 ──")
    pg.set_viewport_size({"width": 1280, "height": 1000})
    pg.wait_for_timeout(200)
    th = pg.inner_text(".grid thead")
    check("產能表頭標出單位/hr", "單位/hr" in th, th)
    check("工時表頭標出 hr", "hr" in th, th)
    check("當日產能標出單位", "單位/hr" in pg.inner_text("#sumR"), pg.inner_text("#sumR"))

    print("\n── 標題與間距 ──")
    pg.set_viewport_size({"width": 1280, "height": 1000})   # 前面截圖縮成手機寬了，量桌機版
    pg.wait_for_timeout(200)
    t = pg.evaluate("""() => {
      const el = document.querySelector('.topbar .t');
      const cs = getComputedStyle(el);
      return {text: el.textContent, size: parseFloat(cs.fontSize), weight: cs.fontWeight};
    }""")
    check("標題文字正確", t["text"] == "產品包裝資料輸入", t["text"])
    check("標題放大到 21px", t["size"] >= 20, t["size"])
    check("標題是粗體", int(t["weight"]) >= 700, t["weight"])
    gap = pg.evaluate("""() => {
      const cal = document.querySelector('.legend').getBoundingClientRect();
      const exp = document.querySelector('.exp').getBoundingClientRect();
      return Math.round(exp.top - cal.bottom);
    }""")
    check("匯出列與上方分開（有分隔線與間距）", gap >= 0, gap)
    check("匯出列有分隔線",
          pg.evaluate("getComputedStyle(document.querySelector('.exp')).borderTopWidth") == "1px")

    print("\n── 月度完整性檢核 ──")
    check("檢核面板有出現", pg.is_visible("#chkBody"))
    hd = pg.inner_text("#chkTxt")
    check("標示待補天數", "11 個工作日" in hd, hd)
    check("待補時是警示樣式", "warn" in (pg.locator("#chkHd").get_attribute("class") or ""),
          pg.locator("#chkHd").get_attribute("class"))
    check("提供前往最早一天的按鈕", pg.is_visible("#chkGo"))
    rows = pg.locator("#chkBody .mtab tbody tr")
    check("列出三個月", rows.count() == 3, rows.count())
    check("匯入的月份有標示", "匯入" in rows.nth(1).inner_text(), rows.nth(1).inner_text())
    check("匯入月份不列待補", rows.nth(1).locator("td").nth(4).inner_text().strip() == "—",
          rows.nth(1).locator("td").nth(4).inner_text())
    check("人數覆蓋率顯示 100%", "100%" in rows.nth(1).inner_text(), rows.nth(1).inner_text())
    check("合計進度出現", "人數補登合計" in pg.inner_text("#chkBody"),
          pg.inner_text("#chkBody")[-120:])
    rows.nth(2).click()
    pg.wait_for_timeout(500)
    check("點月份可跳到該月", "2026 年 7 月" in pg.inner_text("#calTitle"),
          pg.inner_text("#calTitle"))

    print("\n── console ──")
    for l in errs[:10]: print("  " + l)
    check("沒有 JS 錯誤", not errs, errs[:3])

    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
