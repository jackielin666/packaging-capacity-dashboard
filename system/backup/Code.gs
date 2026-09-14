/**
 * 包裝產能資料庫 —— 每月自動備份到 Google Drive
 *
 * 跑在 Google 自己的機器上，不需要開電腦、不需要伺服器、不需要付費。
 * 每月 1 號凌晨把資料庫整份匯出成 CSV，存進指定的 Drive 資料夾。
 *
 * 安裝方式見同資料夾的 README.md。
 */

// ── 設定 ────────────────────────────────────────────────────
// 這裡只放「公開就沒關係」的值。密碼放在指令碼屬性，不寫在程式裡。
var SUPABASE_URL = 'https://vnncuksjvdsxwveomoww.supabase.co';
var ANON_KEY     = 'sb_publishable_Bloy5WhUpWGd7G0Uh_Kmdw_UB4dUNEo';
var FOLDER_ID    = '1FXHhPneNgMc4H11ZzrFbnhF1h-B-v9vq';  // 包裝產能資料庫備份
var BACKUP_EMAIL = 'backup@packing.local';               // 唯讀帳號，只能讀不能寫
var KEEP_MONTHS  = 24;                                   // 保留最近 24 份，更舊的自動刪除

// 要備份的資料表，以及各自的欄位
var TABLES = [
  { name: 'skus',         columns: 'code,name,unit_weight_kg,units_per_record,container,active,note' },
  { name: 'batches',      columns: 'sku_code,prod_date,start_time,end_time,bottles,headcount,note,source' },
  { name: 'daily_status', columns: 'prod_date,no_operation,note' }
];

// ── 主程式 ──────────────────────────────────────────────────

/** 每月自動執行的進入點。也可以手動按「執行」立刻備份一次。 */
function runBackup() {
  var token  = signIn_();
  var folder = DriveApp.getFolderById(FOLDER_ID);
  var stamp  = Utilities.formatDate(new Date(), 'Asia/Taipei', 'yyyyMMdd');
  var report = [];

  TABLES.forEach(function (t) {
    var rows = fetchAll_(token, t.name, t.columns);
    var csv  = toCsv_(rows, t.columns.split(','));
    var file = folder.createFile('packing_' + t.name + '_' + stamp + '.csv', csv, MimeType.CSV);
    report.push(t.name + '：' + rows.length + ' 筆（' + Math.round(csv.length / 1024) + ' KB）');
    Logger.log('已寫入 %s（%s 筆）', file.getName(), rows.length);
  });

  prune_(folder);
  Logger.log('備份完成 —— ' + report.join('、'));
  return report.join('\n');
}

/**
 * 備份完整性檢查：比對 Drive 上最新一份與資料庫現況的筆數。
 * 目的是抓「備份看起來有跑、其實是空檔」這種最危險的情況。
 */
function verifyLatestBackup() {
  var token  = signIn_();
  var folder = DriveApp.getFolderById(FOLDER_ID);
  var lines  = [];

  TABLES.forEach(function (t) {
    var live   = countRows_(token, t.name);
    var latest = newestFile_(folder, 'packing_' + t.name + '_');
    if (!latest) { lines.push('⚠ ' + t.name + '：Drive 上找不到任何備份'); return; }
    // 減 1 是扣掉標題列；空表會匯出成只有標題列的檔案
    var backed = latest.getBlob().getDataAsString().trim().split('\n').length - 1;
    lines.push((backed === live ? '✔ ' : '⚠ ') + t.name +
               '：資料庫 ' + live + ' 筆、備份 ' + backed + ' 筆（' + latest.getName() + '）');
  });

  var msg = lines.join('\n');
  Logger.log(msg);
  return msg;
}

/** 建立每月 1 號的自動執行排程。只需要按一次。 */
function installMonthlyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'runBackup') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runBackup').timeBased().onMonthDay(1).atHour(3).create();
  Logger.log('已排定：每月 1 號凌晨 3 點自動備份');
}

// ── 內部函式 ────────────────────────────────────────────────

/** 用唯讀帳號登入，取得 30 分鐘有效的存取權杖 */
function signIn_() {
  var pw = PropertiesService.getScriptProperties().getProperty('BACKUP_PASSWORD');
  if (!pw) throw new Error('尚未設定 BACKUP_PASSWORD。請到「專案設定 → 指令碼屬性」新增。');

  var res = UrlFetchApp.fetch(SUPABASE_URL + '/auth/v1/token?grant_type=password', {
    method: 'post',
    contentType: 'application/json',
    headers: { apikey: ANON_KEY },
    payload: JSON.stringify({ email: BACKUP_EMAIL, password: pw }),
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) {
    throw new Error('登入失敗（' + res.getResponseCode() + '）：' + res.getContentText());
  }
  return JSON.parse(res.getContentText()).access_token;
}

/** 分頁把整張表讀完。PostgREST 單次有筆數上限，所以要一頁一頁拿。 */
function fetchAll_(token, table, columns) {
  var PAGE = 1000, all = [], from = 0;
  for (;;) {
    var url = SUPABASE_URL + '/rest/v1/' + table +
              '?select=' + encodeURIComponent(columns) +
              '&order=' + encodeURIComponent(columns.split(',')[0]);
    var res = UrlFetchApp.fetch(url, {
      headers: {
        apikey: ANON_KEY,
        Authorization: 'Bearer ' + token,
        'Accept-Profile': 'packing',
        Range: from + '-' + (from + PAGE - 1)
      },
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 400) {
      throw new Error('讀取 ' + table + ' 失敗（' + res.getResponseCode() + '）：' + res.getContentText());
    }
    var page = JSON.parse(res.getContentText());
    all = all.concat(page);
    if (page.length < PAGE) return all;
    from += PAGE;
  }
}

/** 只取筆數，不把資料拉下來 */
function countRows_(token, table) {
  var res = UrlFetchApp.fetch(SUPABASE_URL + '/rest/v1/' + table + '?select=*', {
    headers: {
      apikey: ANON_KEY,
      Authorization: 'Bearer ' + token,
      'Accept-Profile': 'packing',
      Prefer: 'count=exact',
      Range: '0-0'
    },
    muteHttpExceptions: true
  });
  // Content-Range 格式為 "0-0/1593"，斜線後面就是總筆數
  var cr = res.getHeaders()['content-range'] || res.getHeaders()['Content-Range'] || '';
  return parseInt(String(cr).split('/')[1], 10);
}

/** 轉成 CSV。有逗號、引號或換行的欄位一律加引號，引號本身用兩個引號跳脫。 */
function toCsv_(rows, columns) {
  var out = [columns.join(',')];
  rows.forEach(function (r) {
    out.push(columns.map(function (c) {
      var v = r[c];
      if (v === null || v === undefined) return '';
      v = String(v);
      return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    }).join(','));
  });
  return out.join('\n') + '\n';
}

function newestFile_(folder, prefix) {
  var best = null, it = folder.getFiles();
  while (it.hasNext()) {
    var f = it.next();
    if (f.getName().indexOf(prefix) !== 0) continue;
    if (!best || f.getName() > best.getName()) best = f;
  }
  return best;
}

/** 每張表只保留最近 KEEP_MONTHS 份 */
function prune_(folder) {
  TABLES.forEach(function (t) {
    var prefix = 'packing_' + t.name + '_', files = [], it = folder.getFiles();
    while (it.hasNext()) {
      var f = it.next();
      if (f.getName().indexOf(prefix) === 0) files.push(f);
    }
    files.sort(function (a, b) { return b.getName().localeCompare(a.getName()); });
    files.slice(KEEP_MONTHS).forEach(function (f) {
      Logger.log('刪除過舊的備份：%s', f.getName());
      f.setTrashed(true);
    });
  });
}
