/* 包裝產能儀表板 ── 計算引擎
 *
 * 這支檔案是儀表板唯一的計算來源：內建資料與使用者上傳的檔案都走同一條路，
 * 所以不會有「內建數字」跟「上傳後數字」對不起來的問題。
 *
 * 分成三段：
 *   1. readXlsx()  瀏覽器原生解 xlsx（zip + XML），不依賴任何外部套件
 *   2. toBatches() 把工作表整理成逐批次紀錄，還原年份、處理混包寫法
 *   3. analyse()   算出所有指標、燈號與兩條偵測規則
 */
(function (global) {
'use strict';

/* ══════════════ 1. xlsx 解析 ══════════════ */

const SIG_EOCD = 0x06054b50, SIG_CEN = 0x02014b50, SIG_LOC = 0x04034b50;

function supported() {
  return typeof DecompressionStream === 'function' && typeof DOMParser === 'function';
}

async function inflateRaw(bytes) {
  const stream = new Blob([bytes]).stream()
    .pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** 讀 zip 的中央目錄，回傳 {檔名: Uint8Array} 的取檔函式 */
async function openZip(buffer) {
  const view = new DataView(buffer), bytes = new Uint8Array(buffer);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= 0 && i > bytes.length - 66000; i--) {
    if (view.getUint32(i, true) === SIG_EOCD) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('這個檔案不是有效的 Excel 檔（找不到壓縮檔結構）。');

  const count = view.getUint16(eocd + 10, true);
  let offset = view.getUint32(eocd + 16, true);
  if (offset === 0xffffffff) throw new Error('這個 Excel 檔使用了 ZIP64 格式，目前無法讀取。');

  const entries = new Map();
  for (let i = 0; i < count; i++) {
    if (view.getUint32(offset, true) !== SIG_CEN) break;
    const method = view.getUint16(offset + 10, true);
    const compSize = view.getUint32(offset + 20, true);
    const nameLen = view.getUint16(offset + 28, true);
    const extraLen = view.getUint16(offset + 30, true);
    const cmtLen = view.getUint16(offset + 32, true);
    const localAt = view.getUint32(offset + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(offset + 46, offset + 46 + nameLen));
    entries.set(name, { method, compSize, localAt });
    offset += 46 + nameLen + extraLen + cmtLen;
  }

  return async function read(name) {
    const e = entries.get(name);
    if (!e) return null;
    if (view.getUint32(e.localAt, true) !== SIG_LOC) return null;
    const dataAt = e.localAt + 30
      + view.getUint16(e.localAt + 26, true)
      + view.getUint16(e.localAt + 28, true);
    const raw = bytes.subarray(dataAt, dataAt + e.compSize);
    const out = e.method === 0 ? raw : await inflateRaw(raw);
    return new TextDecoder().decode(out);
  };
}

const parseXml = text => new DOMParser().parseFromString(text, 'application/xml');

/** 取一列裡各欄的值；回傳與欄位順序對應的陣列 */
function rowValues(rowEl, shared) {
  const out = [];
  for (const c of rowEl.getElementsByTagName('c')) {
    const ref = c.getAttribute('r') || '';
    const col = ref.replace(/[0-9]/g, '');
    let idx = 0;
    for (let i = 0; i < col.length; i++) idx = idx * 26 + (col.charCodeAt(i) - 64);
    const type = c.getAttribute('t');
    let value = null;
    if (type === 'inlineStr') {
      const t = c.getElementsByTagName('t');
      value = t.length ? t[0].textContent : null;
    } else {
      const v = c.getElementsByTagName('v');
      if (v.length) {
        const raw = v[0].textContent;
        value = type === 's' ? (shared[+raw] ?? null)
              : type === 'str' || type === 'e' ? raw
              : parseFloat(raw);
      }
    }
    out[idx - 1] = value;
  }
  return out;
}

/** 讀出 {sheetName: [[cell,...],...]} */
async function readXlsx(buffer) {
  if (!supported()) throw new Error('unsupported');
  const read = await openZip(buffer);

  const wbText = await read('xl/workbook.xml');
  if (!wbText) throw new Error('這個檔案不是 Excel 活頁簿（缺少 workbook）。');

  const relsText = await read('xl/_rels/workbook.xml.rels') || '';
  const rels = {};
  for (const r of parseXml(relsText).getElementsByTagName('Relationship')) {
    rels[r.getAttribute('Id')] = r.getAttribute('Target').replace(/^\/?xl\//, '');
  }

  const sharedText = await read('xl/sharedStrings.xml');
  const shared = [];
  if (sharedText) {
    for (const si of parseXml(sharedText).getElementsByTagName('si')) {
      let s = '';
      for (const t of si.getElementsByTagName('t')) s += t.textContent;
      shared.push(s);
    }
  }

  const sheets = {};
  for (const sh of parseXml(wbText).getElementsByTagName('sheet')) {
    const name = sh.getAttribute('name');
    const rid = sh.getAttribute('r:id') || sh.getAttributeNS(
      'http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id');
    const target = rels[rid];
    if (!target) continue;
    const text = await read('xl/' + target.replace(/^\.\//, ''));
    if (!text) continue;
    sheets[name] = [...parseXml(text).getElementsByTagName('row')]
      .map(r => rowValues(r, shared));
  }
  return sheets;
}

/* ══════════════ 2. 整理成逐批次紀錄 ══════════════ */

const HEADER = ['包裝日期', '起始時間', '結束時間', '工時', '瓶數'];
const DATE_RE = /^\s*(\d{1,2})月(\d{1,2})日/;

/** 瓶數欄：數字直接用；混包寫法（A200/B209）把所有數字加總 */
function parseBottles(v) {
  if (v == null) return null;
  if (typeof v === 'number') return { n: v, mixed: false };
  const nums = String(v).match(/\d+/g);
  if (!nums) return null;
  return { n: nums.reduce((a, x) => a + +x, 0), mixed: true };
}

/** Excel 日期序號 → {月, 日} */
function serialToMd(serial) {
  const d = new Date(Date.UTC(1899, 11, 30) + Math.round(serial) * 86400000);
  return { mo: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

/**
 * 包裝日期欄沒有年份。資料以 10月→隔年9月 為一個週期排列，
 * 因此 10–12 月屬起始年、1–9 月屬次年。startYear 可由使用者調整。
 */
function toBatches(sheets, startYear) {
  const batches = [], skipped = [], emptySheets = [], badHeader = [];

  for (const [name, rows] of Object.entries(sheets)) {
    if (!rows.length || rows[0][0] == null) { emptySheets.push(name); continue; }
    const head = rows[0].slice(0, 5).map(x => (x == null ? '' : String(x).trim()));
    if (HEADER.some((h, i) => head[i] !== h)) { badHeader.push({ sheet: name, head }); continue; }

    rows.slice(1).forEach((row, i) => {
      const [dateV, , , hoursV, bottlesV] = row;
      if (dateV == null && bottlesV == null) return;   // Excel 預留空列

      let mo = null, day = null;
      if (typeof dateV === 'number') ({ mo, day } = serialToMd(dateV));
      else {
        const m = DATE_RE.exec(String(dateV ?? ''));
        if (m) { mo = +m[1]; day = +m[2]; }
      }
      const bottles = parseBottles(bottlesV);
      const where = { sheet: name, row: i + 2, date: String(dateV ?? '') };

      if (mo == null) return skipped.push({ ...where, why: '日期無法解析' });
      if (typeof hoursV !== 'number') return skipped.push({ ...where, why: '工時空白' });
      if (hoursV <= 0) return skipped.push({ ...where, why: '工時為零或負數' });
      if (!bottles || bottles.n <= 0) return skipped.push({ ...where, why: '瓶數空白' });

      const year = mo >= 10 ? startYear : startYear + 1;
      const iso = `${year}-${String(mo).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      batches.push({
        s: name, d: iso, m: iso.slice(0, 7),
        h: Math.round(hoursV * 1e4) / 1e4,   // 原檔有浮點雜訊，收斂到 4 位
        b: bottles.n, mixed: bottles.mixed,
      });
    });
  }

  if (!batches.length) {
    throw new Error(badHeader.length
      ? `欄位不符。工作表「${badHeader[0].sheet}」的標題是 ${badHeader[0].head.join('、')}，`
        + `應為 ${HEADER.join('、')}。`
      : '這個檔案裡沒有可用的包裝紀錄。');
  }
  batches.sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0));
  return { batches, skipped, emptySheets, badHeader };
}

/** 沒有年份可依循時，用今天推一個合理的起始年度 */
function guessStartYear(today = new Date()) {
  return today.getMonth() + 1 >= 10 ? today.getFullYear() : today.getFullYear() - 1;
}

/* ══════════════ 3. 指標與規則 ══════════════ */

const SHORT_BATCH_H = 1.0;   // 零星批次門檻
// 離群批次：以該品項的平均產能（總瓶數÷總工時）為基準。
// 用平均而非中位數，是因為畫面上顯示、圖上畫線的就是平均產能 —— 門檻可以被使用者驗證。
const OUT_HI = 2.5, OUT_LO = 0.7;
const CV_WATCH = 40;         // 批次落差警戒（%）。實測中位數 35%，25% 會標到八成品項
const DECLINE = 0.9;         // 連續低於自身中位數 10% 以上
const DECLINE_MONTHS = 3;
const MIN_BATCHES = 10;      // 低於此批次數不做判定，只標「批次太少」
const INTENSITY_HIGH = 1.5;  // 相對工時強度
const HOUR_SHARE_HIGH = 3.0; // 工時佔比（%）

const median = a => {
  const s = [...a].sort((x, y) => x - y), i = s.length >> 1;
  return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
};
const quantile = (a, q) => {
  const s = [...a].sort((x, y) => x - y), pos = (s.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (pos - lo);
};
const mean = a => a.reduce((x, y) => x + y, 0) / a.length;
const stdev = a => { const m = mean(a); return Math.sqrt(mean(a.map(x => (x - m) ** 2))); };

function analyse(batches) {
  const totalB = batches.reduce((a, x) => a + x.b, 0);
  const totalH = batches.reduce((a, x) => a + x.h, 0);
  const overallRate = totalB / totalH;

  const bySku = new Map();
  for (const x of batches) {
    if (!bySku.has(x.s)) bySku.set(x.s, []);
    bySku.get(x.s).push(x);
  }

  const allMonths = [...new Set(batches.map(x => x.m))].sort();
  const recent3 = new Set(allMonths.slice(-3));

  const skus = [];
  for (const [sku, list] of bySku) {
    const rates = list.map(x => x.b / x.h);
    const B = list.reduce((a, x) => a + x.b, 0);
    const H = list.reduce((a, x) => a + x.h, 0);
    const rate = B / H, med = median(rates), p75 = quantile(rates, 0.75);
    const days = new Set(list.map(x => x.d)).size;
    const short = list.filter(x => x.h < SHORT_BATCH_H);

    // 離群批次：跟這支產品自己的平均產能比
    const outliers = list
      .filter(x => { const r = x.b / x.h; return r > rate * OUT_HI || r < rate * OUT_LO; })
      .map(x => ({ ...x, rate: x.b / x.h, recent: recent3.has(x.m) }))
      .sort((a, b) => a.d < b.d ? 1 : -1);   // 日期新→舊

    // 落後最多的批次 —— 給現場去查那幾天發生什麼事
    const laggards = list
      .map(x => ({ ...x, rate: x.b / x.h, gap: 1 - (x.b / x.h) / p75 }))
      .filter(x => x.gap > 0)
      .sort((a, b) => b.gap - a.gap)
      .slice(0, 5)
      .sort((a, b) => a.d < b.d ? 1 : -1);   // 取差距最大的 5 批後，改依日期排序

    // 該品項自己的月產能
    const byMonth = new Map();
    for (const x of list) {
      if (!byMonth.has(x.m)) byMonth.set(x.m, [0, 0]);
      const e = byMonth.get(x.m); e[0] += x.b; e[1] += x.h;
    }
    const months = [...byMonth.entries()].sort()
      .map(([m, [b, h]]) => ({ m, b, h: +h.toFixed(2), rate: Math.round(b / h) }));
    const last3 = months.slice(-DECLINE_MONTHS);
    const declining = months.length >= DECLINE_MONTHS
      && last3.every(x => x.rate < med * DECLINE);
    const recentRates = list.filter(x => recent3.has(x.m)).map(x => x.b / x.h);
    const vsUsual = recentRates.length ? mean(recentRates) / med - 1 : null;

    const cv = Math.round(100 * stdev(rates) / mean(rates));
    const enough = list.length >= MIN_BATCHES;
    const recentOutliers = outliers.filter(x => x.recent);
    // 燈號要能自己解釋為什麼 —— 否則「近三月 +1% 卻標異常」會讓人不信任
    let status = 'ok', statusWhy = '批次穩定';
    if (!enough) { status = 'thin'; statusWhy = `全年僅 ${list.length} 批，樣本不足`; }
    else if (declining) { status = 'alert'; statusWhy = '連續 3 個月變慢'; }
    else if (recentOutliers.length) {
      status = 'alert'; statusWhy = `近三月 ${recentOutliers.length} 批離群`;
    } else if (cv > CV_WATCH) { status = 'watch'; statusWhy = `批次落差 ${cv}%`; }

    skus.push({
      sku, b: Math.round(B), h: +H.toFixed(1), d: days, n: list.length,
      rate: Math.round(rate), hPer1k: +(1000 / rate).toFixed(2),
      med: Math.round(med), p75: Math.round(p75),
      best: Math.round(Math.max(...rates)), worst: Math.round(Math.min(...rates)),
      cv, save: +Math.max(H - B / p75, 0).toFixed(1),
      intensity: +(overallRate / rate).toFixed(2),
      hShare: +(100 * H / totalH).toFixed(2), bShare: +(100 * B / totalB).toFixed(2),
      shortN: short.length, shortH: +short.reduce((a, x) => a + x.h, 0).toFixed(1),
      status, statusWhy, declining, vsUsual, months, outliers, laggards,
      recentOutlierN: recentOutliers.length,
    });
  }
  skus.sort((a, b) => b.b - a.b);

  // 每日負載
  const dayH = new Map(), daySku = new Map();
  for (const x of batches) {
    dayH.set(x.d, (dayH.get(x.d) || 0) + x.h);
    const k = x.d + '|' + x.s;
    daySku.set(k, (daySku.get(k) || 0) + x.h);
  }
  const dailyHours = [...dayH.values()];
  const solo8 = [...daySku.entries()].filter(([, h]) => h > 8)
    .map(([k, h]) => ({ date: k.split('|')[0], sku: k.split('|')[1], h: +h.toFixed(2) }))
    .sort((a, b) => b.h - a.h);

  // 全廠每批相對表現（該批產能 ÷ 該品項中位數），讓不同瓶型可以放在同一張圖
  const medBySku = new Map(skus.map(s => [s.sku, s.med]));
  const relative = batches.map(x => ({
    m: x.m, s: x.s, d: x.d, h: x.h, b: x.b,
    rel: (x.b / x.h) / medBySku.get(x.s),
  }));
  const relByMonth = allMonths.map(m => {
    const vals = relative.filter(x => x.m === m).map(x => x.rel);
    return { m, median: +median(vals).toFixed(3), n: vals.length };
  });

  const shortAll = batches.filter(x => x.h < SHORT_BATCH_H);
  const dates = batches.map(x => x.d);
  const meta = {
    period: [dates.reduce((a, b) => a < b ? a : b), dates.reduce((a, b) => a > b ? a : b)],
    records: batches.length, skuCount: skus.length, workDays: dayH.size,
    bottles: Math.round(totalB), hours: +totalH.toFixed(1),
    rate: Math.round(overallRate), hPer1k: +(1000 / overallRate).toFixed(2),
    saveAll: Math.round(skus.reduce((a, s) => a + s.save, 0)),
    shortN: shortAll.length, shortH: Math.round(shortAll.reduce((a, x) => a + x.h, 0)),
    shortShare: Math.round(100 * shortAll.length / batches.length),
    dayMedian: +median(dailyHours).toFixed(1), dayMax: +Math.max(...dailyHours).toFixed(1),
    over8Days: dailyHours.filter(h => h > 8).length,
    solo8, months: allMonths,
    mixedN: batches.filter(x => x.mixed).length,
  };

  return { meta, skus, batches, relative, relByMonth, alerts: buildAlerts(skus, meta) };
}

/* 兩條全廠層級的規則。其餘提醒改在點進單一品項時才出現。 */
function buildAlerts(skus, meta) {
  const out = [];

  const heavy = skus
    .filter(s => s.intensity > INTENSITY_HIGH && s.hShare >= HOUR_SHARE_HIGH)
    .sort((a, b) => b.hShare - a.hShare);
  if (heavy.length) {
    out.push({
      id: 'heavy', level: 'info', owner: '業務 / 生管',
      title: '吃工時但產量不高的品項',
      rule: `每千瓶工時高於全廠平均 ${INTENSITY_HIGH} 倍，且占全廠工時 ${HOUR_SHARE_HIGH}% 以上`,
      why: `這不是包裝作業的問題 —— 瓶型與接單方式決定了它就是慢。`
         + `提供給業務與生管參考：接單與排程時，這類品項的工時成本要先估進去。`
         + `（全廠另有 ${meta.shortN} 批未滿 1 小時，合計 ${meta.shortH} 小時`
         + `＝總工時的 ${Math.round(100 * meta.shortH / meta.hours)}%。）`,
      items: heavy.map(s => ({
        sku: s.sku,
        value: `每千瓶 ${s.hPer1k} 小時，是全廠平均的 ${s.intensity} 倍`,
        detail: `只做了全廠 ${s.bShare}% 的瓶數，卻用掉 ${s.hShare}% 的工時`,
      })),
    });
  }

  const declining = skus.filter(s => s.status !== 'thin' && s.declining)
    .sort((a, b) => a.vsUsual - b.vsUsual);
  if (declining.length) {
    out.push({
      id: 'declining', level: 'high', owner: '包裝單位',
      title: '連續 3 個月比自己平常慢的品項',
      rule: `最近 3 個有生產的月份，月產能全部低於該品項自己的中位數 10% 以上`,
      why: '跟自己比，不受瓶型差異影響，所以這是真的變慢了。點進去看是哪幾批拖累。',
      items: declining.map(s => ({
        sku: s.sku,
        value: `近期比平常慢 ${Math.round(-100 * s.vsUsual)}%`,
        detail: `平常 ${s.med.toLocaleString()} → 最近 `
              + `${s.months.slice(-3).map(m => m.rate.toLocaleString()).join(' / ')} 瓶/工時`,
      })),
    });
  }
  return out;
}

global.PackingEngine = {
  supported, readXlsx, toBatches, analyse, guessStartYear,
  thresholds: { SHORT_BATCH_H, OUT_HI, OUT_LO, CV_WATCH, DECLINE, DECLINE_MONTHS, MIN_BATCHES },
  isOutlier: (batch, sku) => { const r = batch.b / batch.h;
    return r > sku.rate * OUT_HI || r < sku.rate * OUT_LO; },
};
})(window);
