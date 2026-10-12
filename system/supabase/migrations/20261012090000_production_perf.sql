-- 效能修正（2026-10-12）：儀表板讀「品項×月」逾時（statement timeout，8.3 秒）。
--
-- 原因 1：RLS 條件寫成 packing.my_role() is not null，每讀一列就呼叫一次（還要查 members 表）。
--         改成 (select packing.my_role())，每個查詢只算一次。權限完全不變。
-- 原因 2：sku_month 的品名用「每一列各跑一次」的子查詢（packing.skus、production.runs），
--         改成先彙總再 left join。欄位與結果不變。
-- 修正後：同一查詢 8,263 ms → 98 ms；8 月效率指數 102.8、6 月 93.0、D0310 標準 81.5 不變。

alter policy imports_read   on production.imports  using ((select packing.my_role()) is not null);
alter policy imports_write  on production.imports  using ((select packing.my_role()) = 'manager') with check ((select packing.my_role()) = 'manager');
alter policy labour_read    on production.labour   using ((select packing.my_role()) is not null);
alter policy labour_write   on production.labour   using ((select packing.my_role()) = 'manager') with check ((select packing.my_role()) = 'manager');
alter policy runs_read      on production.runs     using ((select packing.my_role()) is not null);
alter policy runs_write     on production.runs     using ((select packing.my_role()) = 'manager') with check ((select packing.my_role()) = 'manager');
alter policy settings_read  on production.settings using ((select packing.my_role()) is not null);
alter policy settings_write on production.settings using ((select packing.my_role()) = 'manager') with check ((select packing.my_role()) = 'manager');

create or replace view production.sku_month with (security_invoker = true) as
with m as (
  select sku_code, to_char(prod_date, 'YYYY-MM') as ym,
         sum(mfg_h)  filter (where usable) as mfg_h,
         sum(fill_h) filter (where usable) as fill_h,
         sum(fg)     filter (where usable) as fg_used,
         count(*)    filter (where usable) as n_used,
         count(*)    filter (where fg is not null or n_labour is not null) as n_batch,
         count(*)    filter (where closed) as n_closed,
         sum(fg)     filter (where closed) as fg_all,
         sum(pots) as pots, sum(semi_est) as semi_est, sum(semi_act) as semi_act,
         sum(labour_h) filter (where not outlier) as labour_h_all,
         sum(coalesce(pots, 0)) filter (where labour_h > 0 and not outlier) as labour_pots
  from production.mfg_batch
  where sku_code not in ('專案', '研發', '-')
  group by 1, 2
),
k as (
  select sku_code, to_char(prod_date, 'YYYY-MM') as ym,
         sum(hours * headcount) filter (where headcount is not null and not outlier) as pack_h,
         sum(bottles)           filter (where headcount is not null and not outlier) as pack_b,
         count(*)               filter (where headcount is not null and not outlier) as n_pack,
         count(*)               filter (where outlier) as n_pack_outlier,
         sum(bottles) as pack_b_all, count(*) as n_pack_all
  from production.pack_scored group by 1, 2
),
j as (select * from m full join k using (sku_code, ym)),
rn as (select sku_code, max(sku_name) as nm from production.runs group by 1)
select j.sku_code, j.ym,
       coalesce(ps.name, rn.nm) as sku_name,
       j.mfg_h, j.fill_h, j.fg_used, j.n_used, j.n_batch, j.n_closed, j.fg_all,
       j.pots, j.semi_est, j.semi_act, j.labour_h_all, j.labour_pots,
       j.pack_h, j.pack_b, j.n_pack, j.n_pack_outlier, j.pack_b_all, j.n_pack_all,
       case when j.fg_used > 0 and j.mfg_h  > 0 then round(j.mfg_h  / j.fg_used * 1000, 3) end as mfg_rate,
       case when j.fg_used > 0 and j.fill_h > 0 then round(j.fill_h / j.fg_used * 1000, 3) end as fill_rate,
       case when j.pack_b  > 0 and j.pack_h > 0 then round(j.pack_h / j.pack_b  * 1000, 3) end as pack_rate,
       case when j.semi_est > 0 then round(j.semi_act / j.semi_est * 100, 2) end as yield_pct,
       case when j.labour_pots > 0 then round(j.labour_h_all / j.labour_pots, 3) end as per_pot_h
from j
left join packing.skus ps on ps.code = j.sku_code
left join rn on rn.sku_code = j.sku_code;
