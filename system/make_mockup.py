"""從真正的 entry.html 產生一份「填好資料、不需要後端」的靜態畫面，
給設計用。因為直接開 entry.html 只會看到登入畫面，主畫面看不到。"""
import json, base64
from playwright.sync_api import sync_playwright

PAGE = "file:///home/user/packaging-capacity-dashboard/entry.html"
OUT  = "/home/user/packaging-capacity-dashboard/design/entry-mockup.html"

def b64u(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
JWT = "x." + b64u({"sub": "11111111-2222-3333-4444-555555555555"}) + ".y"

SKUS = [
    {"code":"D0310","name":"草莓蒟蒻餡(1*6kg)","container":"PE袋","batches":256,"mean_rate":256,"median_rate":295,"last_date":"2026-08-29"},
    {"code":"B2011","name":"＃1花生(1*2.8kg)","container":"馬口鐵","batches":125,"mean_rate":828,"median_rate":912,"last_date":"2026-08-29"},
    {"code":"B1011","name":"＃1草莓(1*3.2kg)","container":"馬口鐵","batches":77,"mean_rate":844,"median_rate":909,"last_date":"2026-08-31"},
    {"code":"A1020","name":"大圓草莓-新(1*440g)","container":"玻璃瓶","batches":50,"mean_rate":1502,"median_rate":1562,"last_date":"2026-08-29"},
    {"code":"D0330","name":"藍莓餡(1*6KG)","container":"PE袋","batches":59,"mean_rate":273,"median_rate":293,"last_date":"2026-08-25"},
]

DAYS = [
    {"prod_date":"2026-09-01","batches":4,"bottles":5200,"hours":6.5,"no_operation":False},
    {"prod_date":"2026-09-02","batches":5,"bottles":7100,"hours":7.0,"no_operation":False},
    {"prod_date":"2026-09-03","batches":3,"bottles":3900,"hours":5.0,"no_operation":False},
    {"prod_date":"2026-09-04","batches":0,"bottles":0,"hours":0,"no_operation":True},
    {"prod_date":"2026-09-07","batches":4,"bottles":6100,"hours":6.0,"no_operation":False},
    {"prod_date":"2026-09-08","batches":2,"bottles":2400,"hours":3.5,"no_operation":False},
    {"prod_date":"2026-09-09","batches":5,"bottles":8200,"hours":7.5,"no_operation":False},
]

ROWS = [
    ("D0310", "08:00", "09:30", "380", "5"),
    ("B2011", "09:30", "12:00", "2100", "5"),
    ("A1020", "13:00", "14:20", "1900", "4"),
    ("D0310", "14:20", "15:00", "45",  "5"),   # 刻意做一筆會被標「偏低」的
]

def route(r):
    u, m = r.request.url, r.request.method
    if "fonts.g" in u:
        return r.abort()
    if "/auth/v1/token" in u:
        return r.fulfill(status=200, content_type="application/json",
                         body=json.dumps({"access_token":JWT,"refresh_token":"rt","expires_in":3600}))
    if "/rest/v1/members" in u:
        return r.fulfill(status=200, content_type="application/json",
                         body=json.dumps([{"display_name":"陳小姐","role":"operator"}]))
    if "/rest/v1/sku_stats" in u:
        return r.fulfill(status=200, content_type="application/json", body=json.dumps(SKUS))
    if "/rest/v1/day_summary" in u:
        return r.fulfill(status=200, content_type="application/json", body=json.dumps(DAYS))
    if "/rest/v1/daily_status" in u:
        return r.fulfill(status=200, content_type="application/json", body="[]")
    if "/rest/v1/batches" in u:
        return r.fulfill(status=200, content_type="application/json", body="[]")
    return r.continue_()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page(viewport={"width":1280,"height":1000})
    pg.route("**/*", route)
    pg.goto(PAGE)
    pg.wait_for_selector("#loginView:not([hidden])", timeout=8000)
    pg.fill("#acc", "chen01"); pg.fill("#pw", "********")
    pg.click("#loginBtn")
    pg.wait_for_selector("#appView:not([hidden])", timeout=8000)

    for i, (sku, st, en, bo, hd) in enumerate(ROWS):
        if i > 0:
            pg.click("#addRow")
        row = pg.locator("#rows tr").nth(i)
        for field, val in (("sku",sku),("start",st),("end",en),("bottles",bo),("head",hd)):
            el = pg.locator("#rows tr").nth(i).locator('input[data-f="%s"]' % field)
            el.fill(val); el.blur()
    pg.wait_for_timeout(400)

    # 把目前的輸入值寫成 HTML 屬性，拿掉所有程式碼，讓檔案能單獨打開
    pg.evaluate("""() => {
      document.getElementById('bootView').remove();
      document.getElementById('loginView').hidden = false;   // 登入畫面也一起交給設計
      document.getElementById('acc').value = 'chen01';
      document.getElementById('pw').value  = '';
      document.querySelectorAll('input').forEach(el => el.setAttribute('value', el.value));
      document.querySelectorAll('script').forEach(el => el.remove());
      document.querySelectorAll('link[rel=preconnect]').forEach(el => el.remove());
    }""")

    html = pg.evaluate("() => '<!doctype html>\\n' + document.documentElement.outerHTML")
    b.close()

HEADER = """<!--
  ════════════════════════════════════════════════════════════════
  包裝資料輸入 —— 靜態設計稿
  ════════════════════════════════════════════════════════════════

  這份檔案是從實際運作的 entry.html 擷取下來的，已填入示範資料、
  移除所有程式碼，所以可以直接打開觀看與改樣式。

  上半部 = 登入畫面　／　下半部 = 主畫面

  ── 改樣式請自由發揮，但這幾樣請保留 ──

  1. 所有 id="..."（例如 #rows、#saveBtn、#cal、#sumB）
     程式靠這些找到元素，改掉畫面就不會動。

  2. 所有 data-f="..."（sku／start／end／bottles／head）
     這是輸入欄位對應到哪個資料欄位。

  3. 表格列的結構：每一列有 8 格，第 6 格是工時、第 7 格是產能，
     這兩格的內容是程式即時算出來填進去的。

  4. class 名稱 bad／low／high／has／none／miss／today／locked
     這些是狀態樣式，程式會動態加減，改名字會失效。

  顏色、字體、間距、圓角、陰影、排版順序 —— 這些都可以隨意改。
-->
"""

open(OUT, "w", encoding="utf-8").write(HEADER + html)
print("已產生：", OUT)
print("大小： %.1f KB" % (len(html)/1024))
