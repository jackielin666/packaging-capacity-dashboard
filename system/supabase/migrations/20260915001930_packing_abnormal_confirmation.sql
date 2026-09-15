-- 現場按下「確認無誤」時記在這裡。
--
-- 為什麼要存進資料庫而不是只留在畫面上：
-- 專員確認「這批真的就是慢」本身就是資訊。儀表板的離群清單日後可以分成
-- 「已由現場確認」與「尚未說明」兩類 —— 這正是「請製造單位說明」的閉環。
alter table packing.batches
  add column abnormal_ok    boolean not null default false,
  add column abnormal_ok_by uuid references auth.users(id),
  add column abnormal_ok_at timestamptz;

comment on column packing.batches.abnormal_ok is
  '現場已確認這批產能雖然偏離平常水準，但數字本身沒有打錯。';
