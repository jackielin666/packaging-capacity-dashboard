-- 「有效日期」改成「製造日期」。
--
-- Jackie 哥決定：產品製成率檔案的第一欄是製造日期，用「品號＋製造日期」對應
-- 最直接，所以包裝紀錄改記製造日期。exp_date 上線期間沒有任何一筆有值，直接移除。
--
-- 規則：
--   ‧ 製造日期不可晚於包裝日期（prod_date）。現場最常見的錯是把紙本上的
--     有效日期抄進來，有效日期一定在未來，這條就擋得住。
--   ‧ 不可早於包裝日期一年以上 —— 多半是年份打錯。
--   ‧ 2026-10-01 起必填（觸發器給中文訊息，CHECK 約束是最後一道保險）；
--     更早的歷史資料不必回頭補。
--
-- 實際套用分兩段，讓切換期間新舊頁面都能存：
--   1. 先加 mfg_date 與範圍檢查，必填改為「mfg_date 或 exp_date 其一」
--   2. 新頁面部署完成後，必填改為只認 mfg_date，並移除 exp_date
-- 本檔是兩段完成後的最終狀態。

alter table packing.batches add column if not exists mfg_date date;

alter table packing.batches drop constraint if exists batches_mfg_date_range;
alter table packing.batches add constraint batches_mfg_date_range check (
  mfg_date is null
  or (mfg_date <= prod_date and mfg_date >= prod_date - interval '1 year')
);

comment on column packing.batches.mfg_date is
  '製造日期。與產品製成率檔案以（品號, 製造日期）對應，串接調理／充填／包裝工時。2026-10-01 起必填。';

create index if not exists batches_sku_mfg_idx
  on packing.batches (sku_code, mfg_date) where mfg_date is not null;

drop trigger if exists batches_require_exp_date on packing.batches;
drop function if exists packing.require_exp_date();

create or replace function packing.require_mfg_date() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if new.prod_date >= date '2026-10-01' and new.mfg_date is null then
    raise exception '2026-10-01 起的批次必須填製造日期（照紙本抄八碼，例如 20261001）。若畫面上沒有「製造日期」欄位，請按 Ctrl+F5 重新整理。'
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

drop trigger if exists batches_require_mfg_date on packing.batches;
create trigger batches_require_mfg_date
  before insert or update on packing.batches
  for each row execute function packing.require_mfg_date();

alter table packing.batches drop constraint if exists batches_exp_date_required;
alter table packing.batches drop constraint if exists batches_mfg_date_required;
alter table packing.batches add constraint batches_mfg_date_required
  check (prod_date < date '2026-10-01' or mfg_date is not null);

-- 有效日期退場（範圍檢查與索引隨欄位一起刪除）
alter table packing.batches drop column if exists exp_date;
