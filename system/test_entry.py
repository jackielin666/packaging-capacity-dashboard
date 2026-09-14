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
        if "/rest/v1/day_summary" in u:
            return r.fulfill(status=200, content_type="application/json", body=json.dumps([
                {"prod_date":"2026-09-01","batches":4,"bottles":5000,"hours":6.0,"no_operation":False},
                {"prod_date":"2026-09-02","batches":0,"bottles":0,"hours":0,"no_operation":True},
                {"prod_date":"2026-09-03","batches":2,"bottles":900,"hours":3.0,"no_operation":False},
            ]))
        return r.continue_()
    return route

fails = []
def check(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(extra)))
    if not cond: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page(viewport={"width":1280,"height":1000})
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
    check("品名自動帶出", "草莓蒟蒻餡" in row.locator(".skuname").inner_text(),
          row.locator(".skuname").inner_text())

    cells = pg.locator("#rows tr").first.locator("td")
    hrs = cells.nth(5).inner_text().strip()
    rate = cells.nth(6).inner_text().strip()
    check("工時 = 1.50", hrs == "1.50", hrs)
    check("產能 = 300（450÷1.5）", rate.startswith("300"), rate)
    check("300 在 D0310 正常範圍內，不標警告", "⚠" not in rate, rate)

    print("\n── 異常提示 ──")
    row.locator('input[data-f="bottles"]').fill("120")
    row.locator('input[data-f="bottles"]').blur()
    rate = pg.locator("#rows tr").first.locator("td").nth(6).inner_text()
    check("80/工時 低於 256×0.7 → 標偏低", "偏低" in rate, rate)

    row.locator('input[data-f="bottles"]').fill("1500")
    row.locator('input[data-f="bottles"]').blur()
    rate = pg.locator("#rows tr").first.locator("td").nth(6).inner_text()
    check("1000/工時 高於 256×2.5 → 標偏高", "偏高" in rate, rate)

    row.locator('input[data-f="sku"]').fill("Z9999")
    row.locator('input[data-f="sku"]').blur()
    rate = pg.locator("#rows tr").first.locator("td").nth(6).inner_text()
    check("批次數不足的品項不標警告", "⚠" not in rate, rate)

    print("\n── 半填的列要擋下來 ──")
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
    check("提示說明原因", "補齊" in pg.inner_text("#dirtyHint"), pg.inner_text("#dirtyHint"))
    check("錯誤欄位標紅", r1.locator("input.bad").count() > 0)

    print("\n── 儲存 ──")
    r1.locator('input[data-f="end"]').fill("1200")
    r1.locator('input[data-f="end"]').blur()
    r1 = pg.locator("#rows tr").nth(1)
    r1.locator('input[data-f="bottles"]').fill("1800")
    r1.locator('input[data-f="bottles"]').blur()
    r1.locator('input[data-f="head"]').fill("5")
    r1.locator('input[data-f="head"]').blur()
    check("補齊後儲存鈕啟用", not pg.is_disabled("#saveBtn"))

    pg.click("#saveBtn")
    pg.wait_for_timeout(1200)
    check("送出一個 POST", len(captured["posts"]) == 1, captured["posts"])
    if captured["posts"]:
        body = captured["posts"][0]
        check("送出兩筆批次", len(body) == 2, body)
        b0 = body[0]
        check("欄位名稱正確", set(b0) == {"sku_code","prod_date","start_time","end_time",
                                          "bottles","headcount"}, list(b0))
        check("不送 hours（資料庫自己算）", "hours" not in b0, list(b0))
        check("時間是 HH:MM", re.match(r"^\d\d:\d\d$", b0["start_time"]) is not None, b0)
        check("沒填人數送 null", body[0]["headcount"] is None, body[0])
        check("有填人數送數字", body[1]["headcount"] == 5, body[1])
    check("顯示已儲存", "已儲存" in pg.inner_text("#banner"), pg.inner_text("#banner"))

    print("\n── 月曆 ──")
    check("月曆有格子", pg.locator("#cal .cell[data-d]").count() >= 28)
    check("9/1 標為已登記", "has" in (pg.locator('#cal .cell[data-d="2026-09-01"]')
                                      .get_attribute("class") or ""))
    check("9/2 標為無作業", "none" in (pg.locator('#cal .cell[data-d="2026-09-02"]')
                                       .get_attribute("class") or ""))
    sub = pg.inner_text("#calSub")
    check("進度摘要有數字", "已登記" in sub and "待補" in sub, sub)

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

    pg.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/entry_desktop.png", full_page=True)
    pg.set_viewport_size({"width":390,"height":900})
    pg.wait_for_timeout(300)
    pg.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/entry_mobile.png", full_page=True)

    # 測試裡故意 abort 掉 Google Fonts（這個容器沒有對外網路），
    # 那筆 ERR_FAILED 是測試環境造成的，不是頁面的問題。
    errs = [l for l in logs
            if ("PAGEERROR" in l or l.startswith("error"))
            and "ERR_FAILED" not in l]
    print("\n── console ──")
    for l in errs[:10]: print("  " + l)
    check("沒有 JS 錯誤", not errs, errs[:3])

    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
