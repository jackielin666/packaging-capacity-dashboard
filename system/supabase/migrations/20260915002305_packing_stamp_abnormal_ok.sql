-- 「確認無誤」的維護規則，三件事一起處理：
--
-- 1. 數字被改過，原本的確認就不再適用 —— 確認的是「那組數字」，不是「這一列」。
-- 2. 但如果同一次更新本身就有表態要設定 abnormal_ok，代表呼叫端是刻意的。
--    不做這個例外的話，專員「改了瓶數又按確認無誤」會被一起清掉，
--    明明按了確認、存完卻發現警告還在。
-- 3. 誰確認、何時確認由資料庫蓋章，不採信前端送來的時間 ——
--    瀏覽器時鐘可能是錯的，而這是稽核用的資訊。
create or replace function packing.clear_abnormal_ok() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
declare was boolean := case when tg_op = 'UPDATE' then old.abnormal_ok else false end;
begin
  if tg_op = 'UPDATE'
     and (new.bottles    is distinct from old.bottles
       or new.start_time is distinct from old.start_time
       or new.end_time   is distinct from old.end_time
       or new.sku_code   is distinct from old.sku_code)
     and new.abnormal_ok is not distinct from old.abnormal_ok then
    new.abnormal_ok := false;
  end if;

  if new.abnormal_ok and not was then
    new.abnormal_ok_by := auth.uid();
    new.abnormal_ok_at := now();
  elsif not new.abnormal_ok then
    new.abnormal_ok_by := null;
    new.abnormal_ok_at := null;
  end if;

  return new;
end $$;

drop trigger if exists batches_clear_abnormal_ok on packing.batches;
create trigger batches_abnormal_ok
  before insert or update on packing.batches
  for each row execute function packing.clear_abnormal_ok();
