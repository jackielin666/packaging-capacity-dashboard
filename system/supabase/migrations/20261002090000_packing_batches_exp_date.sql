-- 每批加上「有效日期」。
--
-- 用途：製成率檔案（調理／充填段）用有效日期辨識是哪一批半成品，包裝紀錄
-- 填上同一個有效日期，兩邊就能用「品號＋有效日期」串起來，每支品項才算得出
-- 調理 → 充填 → 包裝的完整工時。
--
-- 規則：
--   ‧ 可以空白 —— 2026-10 以前的歷史資料沒有這個欄位，由業助從 10 月起回頭補。
--   ‧ 必須晚於生產日期，且不超過生產日期 10 年 —— 擋掉 20270729 打成 20720729
--     這類年份打錯；正常保存期限遠小於 10 年。
--   ‧ 舊月份照樣可以補：guard_operator_scope() 只鎖品項／日期／時間／瓶數，
--     有效日期和人數一樣屬於「補登」，不在鎖定範圍內。
--   ‧ 稽核：write_audit() 整列存 before/after，新欄位自動被記錄。

alter table packing.batches add column if not exists exp_date date;

alter table packing.batches drop constraint if exists batches_exp_date_range;
alter table packing.batches add constraint batches_exp_date_range check (
  exp_date is null
  or (exp_date > prod_date and exp_date <= prod_date + interval '10 years')
);

comment on column packing.batches.exp_date is
  '有效日期。與製成率檔案以（品號, 有效日期）對應，串接調理／充填／包裝工時。可空白。';

-- 對應製成率檔案時用（品號＋有效日期）查
create index if not exists batches_sku_exp_idx
  on packing.batches (sku_code, exp_date) where exp_date is not null;
