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
                 "hours": 1.5, "bottles": 380 + d, "headcount": 5})
for d in range(1, 16):
    LIVE.append({"sku_code": "B2011", "prod_date": "2026-09-%02d" % d,
                 "hours": 2.5, "bottles": 2000 + d, "headcount": 3})
# 刻意放幾批異常，才測得到離群與四象限的判定
LIVE.append({"sku_code": "D0310", "prod_date": "2026-09-16",
             "hours": 2.0, "bottles": 120, "headcount": 5})    # 線體與人均都低
LIVE.append({"sku_code": "D0310", "prod_date": "2026-09-17",
             "hours": 1.5, "bottles": 390, "headcount": 9})    # 線體正常、人均低
LIVE.append({"sku_code": "B2011", "prod_date": "2026-09-18",
             "hours": 2.5, "bottles": 1300, "headcount": 2})   # 線體低、人均正常

# 逐月走勢線、月份×品項熱圖、燈號的「近 3 個生產月」都需要跨月資料；
# 人力分配橫條圖至少要三支品項才畫。以上都不影響 9 月的數字（月報只取當月）。
HIST = []
for ym, mul in (("2026-07", 1.00), ("2026-08", 0.92)):
    for d in range(1, 13):
        HIST.append({"sku_code": "D0310", "prod_date": "%s-%02d" % (ym, d),
                     "hours": 1.5, "bottles": round((380 + d) * mul), "headcount": 5})
        HIST.append({"sku_code": "B2011", "prod_date": "%s-%02d" % (ym, d),
                     "hours": 2.5, "bottles": round((2000 + d) * mul), "headcount": 3})
# 第三支品項：三個月都有做，讓熱圖至少有三列
for ym in ("2026-07", "2026-08", "2026-09"):
    for d in range(1, 13):
        HIST.append({"sku_code": "C1010", "prod_date": "%s-%02d" % (ym, d),
                     "hours": 2.0, "bottles": 900 + d * 3, "headcount": 4})
# 8 月放幾批真的異常的，而且工時都 ≥ 1 小時 —— 短批次不列入主名單，測不到
HIST.append({"sku_code": "D0310", "prod_date": "2026-08-20",
             "hours": 3.0, "bottles": 300, "headcount": 5})    # 線體與人均都低
HIST.append({"sku_code": "B2011", "prod_date": "2026-08-22",
             "hours": 2.5, "bottles": 2010, "headcount": 8})   # 線體正常、人均低
HIST.append({"sku_code": "C1010", "prod_date": "2026-08-26",
             "hours": 2.0, "bottles": 480, "headcount": 2})    # 線體低、人均正常
# 一批工時過短的離群，驗證它被分流到「僅供參考」而不是主名單
HIST.append({"sku_code": "D0310", "prod_date": "2026-08-27",
             "hours": 0.4, "bottles": 40, "headcount": 4})
LIVE = HIST + LIVE
LIVE.sort(key=lambda x: x["prod_date"])

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
    if "/rest/v1/month_status" in u:
        return r.fulfill(status=200, content_type="application/json", body=json.dumps([
            {"ym":"2026-09","is_imported":False,"workdays":13,"logged_days":12,
             "no_op_days":0,"blank_days":1,"missing_days":1,"batches":33,
             "with_headcount":33,"head_pct":100},
        ]))
    if "/rest/v1/skus" in u:
        return r.fulfill(status=200, content_type="application/json", body=json.dumps([
            {"code":"D0310","name":"草莓蒟蒻餡(1*6kg)","container":"PE袋",
             "unit_weight_kg":6.0,"units_per_record":1},
            {"code":"B2011","name":"＃1花生(1*2.8kg)","container":"馬口鐵",
             "unit_weight_kg":2.8,"units_per_record":1},
            {"code":"C1010","name":"藍莓餡(1*9kg)","container":"PE袋",
             "unit_weight_kg":9.0,"units_per_record":1},
        ]))
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

    print("\n── 沒登入：擋在登入畫面 ──")
    check("直接跳出登入視窗", pg.is_visible("#lgForm"))
    check("沒有內建資料可看", calls["batches"] == 0, calls)
    check("原始碼不再夾帶生產明細",
          "PAYLOAD:START" not in open(
              "/home/user/packaging-capacity-dashboard/index.html", encoding="utf-8").read())
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check("沒有資料時關不掉登入視窗（否則是空白頁）", pg.is_visible("#lgForm"))

    tabs = pg.locator(".topbar .tabs a")
    check("頂欄有兩個分頁", tabs.count() == 2, tabs.count())
    check("目前在儀表板且標示為選中",
          "on" in (tabs.nth(1).get_attribute("class") or ""), tabs.nth(1).get_attribute("class"))
    check("另一個連到資料輸入", tabs.nth(0).get_attribute("href") == "entry.html",
          tabs.nth(0).get_attribute("href"))
    check("系統名稱與輸入頁一致", pg.inner_text(".topbar .t") == "包裝產能系統",
          pg.inner_text(".topbar .t"))
    # index.html 一直沒有 charset 宣告，靠瀏覽器猜 —— 改個 CSS 就可能猜錯，整頁變亂碼
    check("有 charset 宣告，中文不會變亂碼", "包裝產能系統" in pg.inner_text(".topbar"),
          pg.inner_text(".topbar")[:60])
    # 兩個分頁按鈕字數不同（4 字 vs 3 字），不設等寬看起來一長一短
    ws = pg.eval_on_selector_all(".tabs a", "es => es.map(e => Math.round(e.offsetWidth))")
    check("兩個分頁按鈕等寬", len(set(ws)) == 1, ws)
    bar = pg.evaluate("getComputedStyle(document.querySelector('.topbar')).backgroundColor")
    check("頂欄底色與輸入頁相同（rgb(10,106,93)）", bar == "rgb(10, 106, 93)", bar)

    print("\n── 密碼錯誤 ──")
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
    check("來源標出資料庫與最後日期", "資料庫" in src and "2026-09-18" in src, src)
    check("確實去讀了資料庫", calls["batches"] >= 1, calls)
    check("已不提供 Excel 上傳", pg.locator("#pickFile").count() == 0)
    check("已移除起始年度選單", pg.locator("#startYear").count() == 0)
    # 會議主體預設看「上一個完整月」—— 當月還沒過完，比絕對量就是比日曆
    check("預設是上一個完整月", "2026 年 8 月" in pg.inner_text("#periodNow"),
          pg.inner_text("#periodNow"))
    opts = pg.eval_on_selector_all("#periodSel option", "es => es.map(e => e.value)")
    check("未完成的月份另成一種模式", "p:2026-09" in opts, opts)
    check("完整月不會被標成本月至今", "m:2026-08" in opts, opts)
    kpi = pg.inner_text("#periodKpi")
    check("概況帶單位", "單位／人·hr" in kpi and "公斤" in kpi, kpi[:200])
    check("KPI 有處理效率", "處理效率" in kpi, kpi[:200])
    check("有本期重點", pg.locator("#hiliteBox .rtab.hl tr").count() > 0)
    # A4 可用寬度只有 695px，比手機斷點 760px 還窄 —— 沒排除 print 的話
    # 整份 PDF 的表格都會退回「一列一張卡片」的手機排版
    css = open("index.html", encoding="utf-8").read()
    check("手機排版不會在列印時觸發", "@media(max-width:760px){" not in css
          and "@media screen and (max-width:760px){" in css)
    check("本期重點允許跨頁", ".hilite { break-inside:auto }" in css)
    # 標題說幾筆就要列幾筆 —— 列表短一截，連那個數字都會被懷疑
    check("重點清單不截斷", "slice(0, 3)" not in css and "over.slice(0, 5)" not in css)
    check("互動工具標記為不列入 PDF", pg.locator("section.noprint").count() == 2,
          pg.locator("section.noprint").count())
    check("有產生 PDF 按鈕", pg.is_visible("#pdfBtn"))

    # 本月至今：絕對量不比較，並且要講出資料截至哪一天
    pg.select_option("#periodSel", "p:2026-09")
    pg.wait_for_timeout(800)
    check("本月至今標示在標題上", "至今" in pg.inner_text("#periodNow"),
          pg.inner_text("#periodNow"))
    note = pg.inner_text("#periodNote")
    check("寫出資料截至哪一天", "資料截至" in note, note[:160])
    check("說明為何不比絕對量", "不與上期比較" in note, note[:200])
    arrows = pg.eval_on_selector_all("#periodKpi .rep-kpi > div",
        "es => es.slice(0,3).filter(e => e.querySelector('.d.up, .d.dn')).length")
    check("本月至今：包裝量／重量／工時都不給箭頭", arrows == 0, arrows)
    rates = pg.eval_on_selector_all("#periodKpi .rep-kpi > div",
        "es => es.slice(3,5).filter(e => e.querySelector('.d.up, .d.dn')).length")
    check("率仍然比較（不受天數影響）", rates >= 1, rates)
    check("畫面上有醒目警語", pg.locator("#hiliteBox .warnbar").count() == 1)

    pg.select_option("#periodSel", "all:")
    pg.wait_for_timeout(700)
    check("切到全期後期間跟著變", "全期" in pg.inner_text("#periodNow"),
          pg.inner_text("#periodNow"))
    pg.select_option("#periodSel", "m:2026-08")
    pg.wait_for_timeout(700)

    # ── 品名：只給品號的表，看的人要先去翻對照表才知道在講哪支產品 ──
    print("\n── 品號旁邊帶出品名 ──")
    ov = pg.inner_text("#tbOverview")
    check("品項總覽帶出品名", "草莓蒟蒻餡" in ov and "花生" in ov, ov[:200])
    check("總覽表頭寫明品號 / 品名", "品名" in pg.inner_text("#overviewTable thead"))
    check("單一品項標題有品名",
          "草莓蒟蒻餡" in pg.inner_text("#skuName") or "花生" in pg.inner_text("#skuName"),
          pg.inner_text("#skuName"))
    check("圖表標題有品名", "蒟蒻" in pg.inner_text("#dotTitle") or "花生" in pg.inner_text("#dotTitle"),
          pg.inner_text("#dotTitle"))
    check("下拉選單有品名", "蒟蒻" in pg.inner_text("#selMain"), pg.inner_text("#selMain")[:160])
    # 搜尋品名要找得到 —— 現場記得住「花生」，不見得記得住 B2011
    pg.fill("#skuSearch", "花生")
    pg.wait_for_timeout(400)
    check("可以用品名搜尋", "1" in pg.inner_text("#searchNote")
          and pg.eval_on_selector("#selMain", "el => el.value") == "B2011",
          pg.inner_text("#searchNote"))
    pg.fill("#skuSearch", "")
    pg.wait_for_timeout(400)

    # ── 燈號：看離群「率」，不是「有沒有離群批次」──
    print("\n── 燈號與正常範圍 ──")
    lg = pg.inner_text("#lampLegend")
    check("燈號說明寫明是比率", "離群批次佔" in lg and "%" in lg, lg[:160])
    check("燈號只看選定的期間", "只看選定的那個期間" in lg, lg[:400])
    check("說明短批次為何不列入", "站不住腳" in lg, lg[:600])
    check("說明水準下移升格成議題", "升格成" in lg, lg[:600])
    # td.dv 不能被上方工具列的 .bar 撞名成 flex，否則橫條會被壓成 0 寬
    dvw = pg.eval_on_selector("#tbOverview td.dv .dvb", "e => e.clientWidth")
    check("偏離橫條畫得出來（寬度 > 0）", dvw > 20, dvw)
    check("橫條有中線基準", pg.locator("#tbOverview td.dv .dvb").count() > 0)
    svg = pg.inner_html("#cDots")
    check("圖上標出平常水準", "平常" in svg, svg[:120])
    check("圖上標出下限", "下限" in svg)
    check("圖上畫出正常範圍帶狀", "<rect" in svg and "opacity=\".055\"" in svg)
    # 「連續變慢」看的是月平均，不是單批 —— 圖上要畫得出來，否則看起來像誤判
    check("圖上有月平均折線", pg.locator("#cDots rect").count() >= 2,
          pg.locator("#cDots rect").count())
    check("圖例說明月平均與散點是兩回事", "月平均那條線是另一回事" in pg.inner_text("#dotLegend"),
          pg.inner_text("#dotLegend")[:200])
    # 一次只看一支
    check("已移除品項比較 A/B", pg.locator("#selCmpA").count() == 0
          and pg.locator("#selCmpB").count() == 0)
    # 名詞定義只有一份（第 11 節），畫面與 PDF 共用
    dfs = pg.inner_text("#defsBox")
    for term in ("平常水準", "合理目標", "離群下限", "全廠水準", "公斤／人·hr"):
        check("定義表有「%s」" % term, term in dfs, dfs[:120])
    check("說明為何用中位數不用平均數", "12.4%" in dfs and "加權平均" in dfs, dfs[-300:])
    # 版面：欄位標題要看得見，內容要垂直置中
    th = pg.eval_on_selector("#overviewTable thead th",
        "e => { const c = getComputedStyle(e); return c.textTransform + '|' + c.fontSize + '|' + c.fontWeight; }")
    check("欄位標題沒有被轉成全大寫", "uppercase" not in th, th)
    check("欄位標題字級夠大且夠粗",
          float(th.split("|")[1].replace("px", "")) >= 11 and int(th.split("|")[2]) >= 600, th)
    va = pg.eval_on_selector("#tbOverview td", "e => getComputedStyle(e).verticalAlign")
    check("表格內容垂直置中", va == "middle", va)

    dl = pg.inner_text("#dotLegend")
    check("圖例寫出正常範圍的兩個端點", "～" in dl and "正常範圍" in dl, dl[:200])
    # 工時／產出散佈圖：固定產能是一條從原點出發的斜線，上下限就變成楔形
    sc = pg.inner_html("#cScatter")
    check("散佈圖畫出上下限楔形", "<path" in sc and "opacity=\".055\"" in sc)
    check("散佈圖標出下限與平常", "下限" in sc and "平常" in sc, sc[:150])
    sl = pg.inner_text("#scatterLegend")
    check("說明三條斜線不是同一種東西", "不是同一種東西" in sl and "合理目標" in sl, sl[:200])
    # 迷你趨勢線
    check("品項總覽有逐月走勢", pg.locator("#tbOverview svg.spark").count() > 0)
    check("走勢線有基準線與末點", "circle" in pg.inner_html("#tbOverview td.sp"),
          pg.inner_html("#tbOverview td.sp")[:120])

    for w in (390, 768, 1440):
        pg.set_viewport_size({"width": w, "height": 900})
        pg.wait_for_timeout(250)
        sw = pg.evaluate("document.documentElement.scrollWidth")
        check("%dpx 沒有橫向捲動" % w, sw <= w, sw)
    pg.set_viewport_size({"width": 1280, "height": 1000})
    pg.wait_for_timeout(200)
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
    check("開頁即自動讀資料庫", "資料庫" in src, src)
    pg2.wait_for_timeout(600)
    who = pg2.inner_text("#dashWho").strip()
    check("頂欄顯示登入者姓名", who == "測試主管", who)
    check("姓名後面不再掛角色", "（" not in who and "(" not in who, who)
    check("不需要再按任何按鈕", calls["batches"] >= 1, calls)
    pg2.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/"
                        "fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/dash_live.png",
                   clip={"x": 0, "y": 0, "width": 1280, "height": 620})
    ctx2.close()

    print("\n── 月報 ──")
    ctx3 = b.new_context(viewport={"width": 1280, "height": 1000})
    ctx3.add_init_script("""
      localStorage.setItem('packing.session', JSON.stringify(
        {access:'%s', refresh:'rt', exp: Date.now() + 3600000}));
    """ % JWT)
    pg3 = ctx3.new_page()
    pg3.on("pageerror", lambda e: errs.append(str(e)))
    pg3.route("**/*", route)
    pg3.goto(PAGE)
    pg3.wait_for_selector("#periodSel option", state="attached", timeout=8000)
    pg3.wait_for_timeout(1200)

    opts = pg3.locator("#periodSel option").count()
    check("期間選單有月份與全期", opts >= 3, opts)
    first = pg3.locator("#periodSel option").first.inner_text()
    check("尚未結束的月份排最前面且標示至今", "至今" in first, first)

    pg3.select_option("#periodSel", "m:2026-08")
    pg3.wait_for_timeout(800)
    body = pg3.inner_text(".wrap")
    check("標題是所選期間", "2026 年 8 月" in pg3.inner_text("#periodNow"),
          pg3.inner_text("#periodNow"))
    check("有本期概況", "本期概況" in body)
    check("有品項狀態總覽", "品項狀態總覽" in body)
    check("有需要說明的批次", "需要說明的批次" in body)
    import re as _re
    check("情況欄標出差距百分比",
          _re.search(r"(低於|高於)平常 \d+%", pg3.inner_text("#oddBox")) is not None,
          pg3.inner_text("#oddBox")[:200])
    check("有吃工時的品項段落", "吃工時但產量不高" in body)
    check("標明責任歸屬", "不是包裝作業的問題" in body)

    rows = pg3.locator("#tbOverview tr").count()
    check("品項表有資料", rows > 0, rows)
    # 8 月共 36 批
    check("批次數與資料一致", "40 批" in pg3.inner_text("#periodNow"),
          pg3.inner_text("#periodNow"))

    check("產生 PDF 按鈕存在", pg3.is_visible("#pdfBtn"))
    check("列印抬頭帶入期間", "2026 年 8 月" in pg3.inner_html("#printHead"),
          pg3.inner_html("#printHead")[:160])
    check("表頭標出效率單位", "單位／人·hr" in pg3.inner_text("#overviewTable thead"),
          pg3.inner_text("#overviewTable thead")[:200])
    check("平常水準說明是中位數", "中位數" in body)
    check("有資料完整性段落", "資料完整性" in body)
    pg3.wait_for_timeout(700)
    check("完整性段落讀得到資料", "應登記工作日" in pg3.inner_text("#chkBox"),
          pg3.inner_text("#chkBox")[:120])

    check("表格帶品名", body.count("草莓蒟蒻餡") >= 1 and "花生" in body, body[:200])
    check("本期重點的品項是條列", pg3.locator("#hiliteBox .hlist li").count() > 0,
          pg3.locator("#hiliteBox .hlist li").count())
    check("帶同一份名詞定義", "數字怎麼算的" in body and "合理目標" in body)

    print("\n── 圖表 ──")
    check("有批次落點圖", pg3.locator("#oddBox .rep-fig svg").count() > 0)
    figleg = pg3.inner_text("#oddBox .rep-figleg")
    check("落點圖說明 Y 軸是相對自己的倍率", "平常水準" in figleg, figleg[:160])
    # 人力橫條圖已移除（沒有結論）；逐支品項的處理效率改放在第 03 節
    check("已移除人力分配橫條圖", pg3.locator("#labBox .lbt").count() == 0)
    check("總覽有處理效率欄", "單位／人·hr" in pg3.inner_text("#overviewTable thead"),
          pg3.inner_text("#overviewTable thead")[:200])
    cost = pg3.inner_text("#heavyBox")
    check("工時成本表兩個單位並列", "每千單位工時" in cost and "每千公斤工時" in cost, cost[:200])
    check("工時成本表不做好壞判定", "不做好壞判定" in cost, cost[-400:])
    check("工時成本表點名收件者", "業務" in cost and "生管" in cost, cost[-400:])
    check("有月份 × 品項熱圖", pg3.locator("#heatBox .heat tbody tr").count() > 0,
          pg3.locator("#heatBox .heat").count())
    check("熱圖有色階圖例", "該月沒有生產" in pg3.inner_text("#heatBox .heatleg"),
          pg3.inner_text("#heatBox .heatleg")[:120])
    check("熱圖說明要橫著讀", "橫著讀" in pg3.inner_text("#heatBox"))
    check("表頭寫明品號 / 品名", "品號 / 品名" in pg3.inner_html(".wrap"))

    print("\n── 本期重點 ──")
    hl = pg3.inner_text("#hiliteBox")
    check("有本期重點區塊", "本期重點" in hl, hl[:60])
    check("第一條講產出與效率", "公斤" in hl and "工時" in hl, hl[:160])
    check("條目標出負責單位", any(w in hl for w in ("製造", "生管", "業務", "管理層")), hl[:400])
    rows_hl = pg3.locator("#hiliteBox .rtab.hl tbody tr").count()
    check("重點不超過 6 條", 1 <= rows_hl <= 6, rows_hl)

    print("\n── 人均產能 ──")
    lb = pg3.inner_text("#labBox")
    check("有人均產能段落", "人力與工時分配" in body, body[:1500])
    check("兩個人均指標都在", "單位／人·hr" in lb and "公斤／人·hr" in lb, lb[:600])
    check("hr 沒有被強制變成大寫 HR", "人·HR" not in body,
          [l for l in body.split("\n") if "人·HR" in l][:2])
    check("標出人數覆蓋率", "覆蓋率" in lb, lb[:600])
    check("說明處理效率不可跨品項排名", "不可跨品項排名" in lb, lb[:600])
    full = pg3.inner_text(".wrap")
    check("四象限診斷有出現",
          "線性正常，每人處理量偏低" in full or "線性偏低，每人處理量正常" in full, lb[:300])
    check("不再用「線體」這個現場聽不懂的詞", "線體" not in full, "")
    check("診斷標出負責單位", "包裝班" in full or "生管排班" in full, lb[:300])
    check("需要說明的批次最多 12 筆",
          pg3.locator("#oddBox .rtab tbody tr").count() <= 12,
          pg3.locator("#oddBox .rtab tbody tr").count())
    check("沒有跑出多餘的引號或加號", "' + '" not in body and "+ '" not in body,
          [l for l in body.split("\n") if "+ '" in l][:2])
    kpitxt = pg3.inner_text("#periodKpi")
    check("KPI 的比較文字不會斷行", "對比上\n月" not in kpitxt, kpitxt[:120])
    pg3.screenshot(path="/tmp/claude-0/-home-user-packaging-capacity-dashboard/"
                        "fae20c10-d8ac-59cc-87ad-7eb93e78031d/scratchpad/report.png",
                   full_page=True)
    ctx3.close()

    print("\n── console ──")
    real = [e for e in errs if "ERR_FAILED" not in e]
    check("沒有 JS 錯誤", not real, real[:2])
    b.close()

print("\n" + ("全部通過" if not fails else "失敗 %d 項：%s" % (len(fails), fails)))
