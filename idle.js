/* 閒置 15 分鐘自動登出 —— entry.html 與 dashboard.html 共用。
 *
 * 現場電腦是共用的，登入狀態存在瀏覽器裡、隔天打開還在。
 * 有人離開座位，下一個人就能用他的帳號改資料。所以：
 *
 *   ‧ 15 分鐘沒有任何操作（滑鼠、鍵盤、觸控、捲動）就登出
 *   ‧ 登出前 1 分鐘跳出提醒，動一下就繼續；有沒存的資料會特別講
 *   ‧ 「最後操作時間」存在 localStorage，同一台電腦開了兩個分頁（輸入頁＋儀表板）
 *     只要其中一頁有在操作，兩頁都不會被登出；一頁登出，另一頁跟著登出
 *   ‧ 關掉瀏覽器隔天再開，若已超過 15 分鐘，一打開就是登入畫面
 *
 * 頁面用法：
 *   PackingIdle.expireIfStale()   載入時、讀取登入狀態之前呼叫：過期就先清掉
 *   PackingIdle.start({ hasUnsaved, onLogout })   登入後呼叫
 *   PackingIdle.takeNotice()      登入畫面呼叫：剛才是不是因為閒置被登出（回傳說明文字或 null）
 */
(function () {
  var LIMIT = 15 * 60 * 1000;          // 閒置多久登出
  var WARN = 60 * 1000;                // 登出前多久提醒
  var SS = 'packing.session';          // 與兩個頁面相同的登入狀態
  var LAST = 'packing.lastActive';     // 最後一次操作的時間（各分頁共用）
  var NOTICE = 'packing.idleLoggedOut';
  var API = 'https://vnncuksjvdsxwveomoww.supabase.co';
  var KEY = 'sb_publishable_Bloy5WhUpWGd7G0Uh_Kmdw_UB4dUNEo';

  var opts = null, timer = null, box = null, lastWrite = 0;

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function del(k) { try { localStorage.removeItem(k); } catch (e) {} }
  function lastActive() { var v = Number(get(LAST)); return v > 0 ? v : 0; }

  function touch() {
    var now = Date.now();
    if (now - lastWrite < 5000) return;          // 滑鼠一直動時不要每次都寫
    lastWrite = now;
    set(LAST, String(now));
    hideWarning();
  }

  /** 撤銷這組登入（讓別人複製走的權杖也失效），再清掉本機狀態。 */
  function signOut(reason) {
    var s = null;
    try { s = JSON.parse(get(SS) || 'null'); } catch (e) {}
    if (s && s.access) {
      try {
        fetch(API + '/auth/v1/logout', { method: 'POST', keepalive: true,
          headers: { apikey: KEY, Authorization: 'Bearer ' + s.access } }).catch(function () {});
      } catch (e) {}
    }
    del(SS); del(LAST);
    if (reason) { try { sessionStorage.setItem(NOTICE, reason); } catch (e) {} }
  }

  function logout(reason) {
    stop();
    signOut(reason);
    if (opts && opts.onLogout) opts.onLogout(); else location.reload();
  }

  function warningBox() {
    if (box) return box;
    box = document.createElement('div');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-live', 'assertive');
    box.id = 'idleWarn';
    box.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:9999;'
      + 'max-width:min(560px,calc(100vw - 32px));background:#1d2327;color:#fff;border-radius:6px;'
      + 'padding:14px 18px;font:14px/1.6 "Noto Sans TC",sans-serif;box-shadow:0 8px 28px rgba(0,0,0,.28)';
    box.hidden = true;
    document.body.appendChild(box);
    return box;
  }
  function showWarning(secs) {
    var b = warningBox();
    var unsaved = opts && opts.hasUnsaved && opts.hasUnsaved();
    b.textContent = '';
    var t = document.createElement('b');
    t.textContent = '閒置太久，' + secs + ' 秒後自動登出。';
    b.appendChild(t);
    b.appendChild(document.createTextNode(unsaved
      ? '　這一頁有尚未儲存的資料，請先按「儲存本日」。動一下滑鼠或按任意鍵即可繼續。'
      : '　動一下滑鼠或按任意鍵即可繼續使用。'));
    b.hidden = false;
  }
  function hideWarning() { if (box) box.hidden = true; }

  function check() {
    if (!get(SS)) { logout(null); return; }        // 別的分頁已經登出了
    var idle = Date.now() - (lastActive() || Date.now());
    if (idle >= LIMIT) { logout('閒置超過 15 分鐘，已自動登出，請重新登入。'); return; }
    if (idle >= LIMIT - WARN) showWarning(Math.ceil((LIMIT - idle) / 1000));
    else hideWarning();
  }

  var EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll'];
  function onStorage(e) {
    if (e.key === SS && !e.newValue) logout(null);     // 另一個分頁登出
    if (e.key === LAST) check();
  }
  function onVisible() { if (!document.hidden) check(); }

  function start(o) {
    opts = o || {};
    if (timer) return;
    lastWrite = 0; touch();
    EVENTS.forEach(function (ev) { addEventListener(ev, touch, { passive: true, capture: true }); });
    addEventListener('storage', onStorage);
    document.addEventListener('visibilitychange', onVisible);
    timer = setInterval(check, 1000);
  }
  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
    EVENTS.forEach(function (ev) { removeEventListener(ev, touch, { capture: true }); });
    removeEventListener('storage', onStorage);
    document.removeEventListener('visibilitychange', onVisible);
    hideWarning();
  }

  /** 載入時呼叫：上次操作已超過 15 分鐘（例如隔天才打開），登入狀態直接作廢。 */
  function expireIfStale() {
    if (!get(SS)) return false;
    var last = lastActive();
    if (last && Date.now() - last >= LIMIT) {
      signOut('上次操作已超過 15 分鐘，請重新登入。');
      return true;
    }
    return false;
  }

  function takeNotice() {
    var m = null;
    try { m = sessionStorage.getItem(NOTICE); sessionStorage.removeItem(NOTICE); } catch (e) {}
    return m;
  }

  window.PackingIdle = { start: start, stop: stop, expireIfStale: expireIfStale,
                         takeNotice: takeNotice, signOut: signOut, LIMIT: LIMIT };
})();
