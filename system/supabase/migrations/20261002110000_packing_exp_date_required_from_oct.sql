-- 2026-10-01 起的批次「必須」有有效日期 —— 資料庫層再把關一次。
--
-- 輸入頁已經擋了，但只靠畫面不夠：瀏覽器還留著舊版頁面（沒有有效日期欄位）、
-- 或其他程式直接寫入時，都會繞過畫面上的檢查。沒有有效日期的批次對不到
-- 製成率檔案，算不出調理／充填／包裝的完整工時，所以在資料庫層一律擋下。
--
-- 觸發器負責給現場看得懂的中文訊息；CHECK 約束是最後一道保險。
-- 套用時 10 月尚無任何批次，既有資料全部符合。

create or replace function packing.require_exp_date() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if new.prod_date >= date '2026-10-01' and new.exp_date is null then
    raise exception '2026-10-01 起的批次必須填有效日期（照紙本抄八碼，例如 20270729）。若畫面上沒有「有效日期」欄位，請按 Ctrl+F5 重新整理。'
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

drop trigger if exists batches_require_exp_date on packing.batches;
create trigger batches_require_exp_date
  before insert or update on packing.batches
  for each row execute function packing.require_exp_date();

alter table packing.batches drop constraint if exists batches_exp_date_required;
alter table packing.batches add constraint batches_exp_date_required
  check (prod_date < date '2026-10-01' or exp_date is not null);
