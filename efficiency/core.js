/* 品項全流程工時成本：各頁共用的連線、登入與小工具。
 *
 * 登入沿用包裝系統的帳號與同一個 localStorage 鍵（packing.session）：
 * 同一個網站（jackielin666.github.io）底下，在包裝系統登入過，這裡就不用再登入。
 * 寫法刻意與 entry.html 相同，兩邊行為一致、出問題時查一處就懂另一處。
 */
'use strict';

var API  = 'https://vnncuksjvdsxwveomoww.supabase.co';
var KEY  = 'sb_publishable_Bloy5WhUpWGd7G0Uh_Kmdw_UB4dUNEo';
var MAIL = '@packing.local';
var SS   = 'packing.session';

// ── 小工具 ────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }
/** 建立元素。文字一律走 textNode，不用 innerHTML —— 品名、料號來自 Excel，視為不可信資料。 */
function h(tag, attrs) {
  var e = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach(function (k) {
    var v = attrs[k];
    if (v == null || v === false) return;
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  });
  for (var i = 2; i < arguments.length; i++) append(e, arguments[i]);
  return e;
}
function append(e, k) {
  if (k == null || k === false) return;
  if (Array.isArray(k)) { k.forEach(function (x) { append(e, x); }); return; }
  e.append(k instanceof Node ? k : document.createTextNode(String(k)));
}
function fmt(v, d) {
  if (v == null || !isFinite(v)) return '–';
  return Number(v).toLocaleString('zh-TW', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
}

// ── 連線 ──────────────────────────────────────────────────
var sess = null;
function loadSession() {
  try { sess = JSON.parse(localStorage.getItem(SS) || 'null'); } catch (e) { sess = null; }
  return sess;
}
function saveSession(s) {
  sess = s;
  try { localStorage.setItem(SS, JSON.stringify(s)); } catch (e) {}
}
function clearSession() {
  sess = null;
  try { localStorage.removeItem(SS); } catch (e) {}
}
function jwtSub(tok) {
  try {
    var b = tok.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    while (b.length % 4) b += '=';
    return JSON.parse(decodeURIComponent(escape(atob(b)))).sub;
  } catch (e) { return null; }
}

var DB_HOST = API.replace(/^https?:\/\//, '');
/** 連不上時，把 Failed to fetch 翻成現場看得懂的話（與 entry.html 相同） */
function netFetch(url, opts) {
  return fetch(url, opts).catch(function () {
    throw new Error('連不到資料庫（' + DB_HOST + '）。\n這不是帳號密碼的問題 —— 是這台電腦連不出去。\n'
      + '請先確認網路正常；若其他網站開得起來，請 IT 把這個網址加入白名單。');
  });
}

function signIn(account, password) {
  return netFetch(API + '/auth/v1/token?grant_type=password', {
    method: 'POST',
    headers: { apikey: KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: account.trim().toLowerCase() + MAIL, password: password })
  }).then(function (r) {
    return r.json().then(function (j) {
      if (!r.ok) throw new Error(j.error_description || j.msg || ('登入失敗（' + r.status + '）'));
      saveSession({ access: j.access_token, refresh: j.refresh_token, exp: Date.now() + (j.expires_in || 3600) * 1000 });
      return j;
    });
  });
}

function refresh() {
  if (!sess || !sess.refresh) return Promise.reject(new Error('no session'));
  return netFetch(API + '/auth/v1/token?grant_type=refresh_token', {
    method: 'POST',
    headers: { apikey: KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: sess.refresh })
  }).then(function (r) {
    if (!r.ok) throw new Error('session expired');
    return r.json();
  }).then(function (j) {
    saveSession({ access: j.access_token, refresh: j.refresh_token, exp: Date.now() + (j.expires_in || 3600) * 1000 });
  });
}

/**
 * 呼叫資料 API。schema 預設 production；讀角色時傳 'packing'。
 * 權杖快過期先換新；仍被打回 401 就換一次再重試。
 */
function api(path, opts, retried) {
  opts = opts || {};
  var schema = opts.schema || 'production';
  var pre = (!sess || sess.exp - Date.now() < 60000) ? refresh() : Promise.resolve();
  return pre.catch(function () {}).then(function () {
    var hd = { apikey: KEY, Authorization: 'Bearer ' + (sess ? sess.access : ''),
               'Accept-Profile': schema, 'Content-Profile': schema };
    if (opts.body) hd['Content-Type'] = 'application/json';
    if (opts.prefer) hd.Prefer = opts.prefer;
    return netFetch(API + '/rest/v1/' + path, { method: opts.method || 'GET', headers: hd, body: opts.body });
  }).then(function (r) {
    if (r.status === 401 && !retried) return refresh().then(function () { return api(path, opts, true); });
    if (!r.ok) {
      return r.text().then(function (t) {
        var m = t;
        try { var j = JSON.parse(t); m = j.message || j.hint || j.details || t; } catch (e) {}
        var err = new Error(m + '（' + r.status + '）'); err.status = r.status; throw err;
      });
    }
    if (r.status === 204) return null;
    return r.text().then(function (t) { return t ? JSON.parse(t) : null; });
  });
}

/** 目前登入者的名稱與角色（角色表在 packing schema） */
function whoAmI() {
  var id = sess && jwtSub(sess.access);
  if (!id) return Promise.resolve(null);
  return api('members?select=display_name,role&user_id=eq.' + id, { schema: 'packing' })
    .then(function (rows) { return rows && rows[0] ? rows[0] : null; });
}

// ── 深色／淺色切換（各頁共用）──────────────────────────────
function toggleTheme() {
  var r = document.documentElement;
  var dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('pe-theme', r.dataset.theme); } catch (e) {}
}
(function () { try { var t = localStorage.getItem('pe-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) {} })();
