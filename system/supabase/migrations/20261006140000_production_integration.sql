-- 步驟 4：整合計算。製造／充填（production）＋包裝（packing）→ 品項 × 月份的標準與效率。
--
-- 全部是 view（security_invoker：照登入者的權限讀，RLS 仍有效），只給已登入的成員讀。
-- 參數都在 production.settings，改參數不必改程式。
--
-- 資料流：
--   labour_check ─┬─ labour_run（有效列＋共用作業時段依鍋數分攤）
--                 └─ labour_scored（離群：每鍋人時，沿用製成率系統）
--   runs ＋ labour_scored → mfg_batch（料號＋日期＝一個製造批；結案、可用於計算）
--   packing.batches → pack_scored（離群：每批產能 vs 品項中位數，沿用包裝儀表板 v4）
--   mfg_batch ＋ pack_scored → sku_month → sku_std（基準期中位數）→ sku_eff → plant_month
--   month_gate（三項門檻）、balance_check（物料平衡）、labour_issues（待修正清單）
--   batch_link（2026/10 起以製造日期串接包裝）

insert into production.settings (key, value, note) values
  ('pack_outlier', '{"lo": 0.5, "hi": 2.5, "min_h": 1}',
   '包裝離群批次（沿用包裝儀表板 v4）：每批產能 ÷ 該品項中位數 < lo 或 > hi，且工時 ≥ min_h')
on conflict (key) do nothing;

-- ── 1. 有效工時列（含共用作業時段）──────────────────────────────
-- 共用作業時段：同一天、Excel 上下相鄰兩列，前一列某段只有開始、後一列同一段只有結束
-- （例：2026/9/23 A2050 07:00–、A2060 –14:40）。兩列合成一段計算，再依鍋數分攤。
create view production.labour_run with (security_invoker = true) as
with base as (
  select c.id, c.prod_date, c.sku_code, c.seq, c.sku_name, c.pots, c.status, c.src_row,
         c.mfg_person_min, c.fill_person_min, c.person_min,
         l.mfg_start, l.mfg_end, l.mfg_people, l.mfg_prep_min,
         l.fill_start, l.fill_end, l.fill_people, l.fill_prep_min
  from production.labour_check c join production.labour l on l.id = c.id
),
pair as (
  select a.id as a_id, b.id as b_id, coalesce(a.pots, 0) as a_pots, coalesce(b.pots, 0) as b_pots,
    production.stage_min(coalesce(a.mfg_start, b.mfg_start), coalesce(b.mfg_end, a.mfg_end),
                         (coalesce(a.mfg_prep_min, 0) + coalesce(b.mfg_prep_min, 0))::smallint)
      * coalesce(a.mfg_people, b.mfg_people) as mpm,
    production.stage_min(coalesce(a.fill_start, b.fill_start), coalesce(b.fill_end, a.fill_end),
                         (coalesce(a.fill_prep_min, 0) + coalesce(b.fill_prep_min, 0))::smallint)
      * coalesce(a.fill_people, b.fill_people) as fpm
  from base a
  join base b on b.prod_date = a.prod_date and b.src_row = a.src_row + 1
  where a.status = 'invalid' and b.status = 'invalid'
    and ((a.mfg_start  is not null and a.mfg_end  is null and b.mfg_start  is null and b.mfg_end  is not null)
      or (a.fill_start is not null and a.fill_end is null and b.fill_start is null and b.fill_end is not null))
),
pair_ok as (
  select * from pair
  where mpm is not null and fpm is not null and mpm > 0 and fpm > 0 and a_pots + b_pots > 0
),
shared as (
  select p.a_id as id, round(p.mpm * p.a_pots / (p.a_pots + p.b_pots), 1) as mpm, round(p.fpm * p.a_pots / (p.a_pots + p.b_pots), 1) as fpm from pair_ok p
  union all
  select p.b_id,       round(p.mpm * p.b_pots / (p.a_pots + p.b_pots), 1),       round(p.fpm * p.b_pots / (p.a_pots + p.b_pots), 1)       from pair_ok p
)
select b.id, b.prod_date, b.sku_code, b.seq, b.sku_name, b.pots,
       b.mfg_person_min, b.fill_person_min, b.person_min, 'row'::text as source, b.src_row
from base b where b.status = 'ok'
union all
select b.id, b.prod_date, b.sku_code, b.seq, b.sku_name, b.pots,
       s.mpm, s.fpm, s.mpm + s.fpm, 'shared', b.src_row
from shared s join base b on b.id = s.id;
comment on view production.labour_run is
  '納入計算的工時列：檢核通過的列，加上共用作業時段（相鄰兩列合併後依鍋數分攤，source = shared）';

-- ── 2. 離群（每鍋人時）───────────────────────────────────────
create view production.labour_scored with (security_invoker = true) as
with p as (
  select (value->>'min_n')::int as min_n, (value->>'mz')::numeric as mz,
         (value->>'dev')::numeric as dev, (value->>'cap')::numeric as cap
  from production.settings where key = 'outlier'
),
v as (
  select r.id, r.sku_code, r.person_min / 60.0 / r.pots as v
  from production.labour_run r
  where r.pots > 0 and r.sku_code not in ('專案', '研發', '-') and coalesce(r.sku_name, '') <> '#N/A'
),
s as (select sku_code, count(*) as n, percentile_cont(0.5) within group (order by v) as med from v group by 1),
d as (select v.*, s.n, s.med, abs(v.v - s.med) as ad from v join s using (sku_code)),
m as (select sku_code, percentile_cont(0.5) within group (order by ad) as mad from d group by 1),
c as (
  select d.id, d.sku_code, d.n, 0.6745 * (d.v - d.med) / m.mad as mz
  from d join m using (sku_code) cross join p
  where d.n >= p.min_n and m.mad > 0 and d.med > 0
    and abs(0.6745 * (d.v - d.med) / m.mad) >= p.mz and abs(d.v - d.med) / d.med >= p.dev
),
r as (select c.*, row_number() over (partition by c.sku_code order by abs(c.mz) desc) as rn from c),
o as (select r.id from r cross join p where r.rn <= greatest(1, floor(r.n * p.cap)))
select l.*, (o.id is not null) as outlier
from production.labour_run l left join o on o.id = l.id;
comment on view production.labour_scored is
  '納入計算的工時列＋離群標記。離群以每鍋人時判定（參數 settings.outlier，沿用製成率系統）';

-- ── 3. 製造批（料號＋日期）──────────────────────────────────
create view production.mfg_batch with (security_invoker = true) as
with l as (
  select sku_code, prod_date, count(*) as n_labour, bool_or(outlier) as has_outlier,
         sum(mfg_person_min) / 60.0 as mfg_h, sum(fill_person_min) / 60.0 as fill_h,
         sum(person_min) / 60.0 as labour_h, sum(pots) as labour_pots
  from production.labour_scored group by 1, 2
),
bad as (
  select c.sku_code, c.prod_date, count(*) as n_bad
  from production.labour_check c
  where c.status = 'invalid' and not exists (select 1 from production.labour_run r where r.id = c.id)
  group by 1, 2
),
r as (
  select sku_code, prod_date, max(sku_name) as sku_name, count(*) as n_runs,
         count(*) filter (where fg_act > 0) as n_fg, sum(fg_act) as fg, sum(pots) as pots,
         sum(semi_est) filter (where semi_est > 0 and semi_act > 0) as semi_est,
         sum(semi_act) filter (where semi_est > 0 and semi_act > 0) as semi_act
  from production.runs group by 1, 2
)
select sku_code, prod_date, r.sku_name, r.pots, r.fg, r.semi_est, r.semi_act,
       coalesce(r.n_runs > 0 and r.n_fg = r.n_runs, false) as closed,
       l.mfg_h, l.fill_h, l.labour_h, l.n_labour,
       coalesce(l.has_outlier, false) as outlier,
       coalesce(bad.n_bad, 0) as labour_bad,
       coalesce(r.n_runs > 0 and r.n_fg = r.n_runs and l.labour_h > 0
                and not l.has_outlier and coalesce(bad.n_bad, 0) = 0, false) as usable
from r full join l using (sku_code, prod_date)
left join bad using (sku_code, prod_date);
comment on view production.mfg_batch is
  '製造批（料號＋生產日期）。closed＝成品數已填；usable＝已結案、有工時、無離群、無異常工時列，才用於人時/千瓶';

-- ── 4. 包裝批次＋離群 ─────────────────────────────────────────
create view production.pack_scored with (security_invoker = true) as
with p as (
  select (value->>'lo')::numeric as lo, (value->>'hi')::numeric as hi, (value->>'min_h')::numeric as min_h
  from production.settings where key = 'pack_outlier'
),
b as (
  select id, sku_code, prod_date, mfg_date, hours, bottles, headcount, bottles / hours as rate
  from packing.batches where hours > 0
),
s as (select sku_code, percentile_cont(0.5) within group (order by rate) as med from b group by 1)
select b.*, s.med as sku_median_rate,
       (b.hours >= p.min_h and (b.rate < s.med * p.lo or b.rate > s.med * p.hi)) as outlier
from b join s using (sku_code) cross join p;
comment on view production.pack_scored is
  '包裝批次＋離群標記（每批產能 vs 品項中位數，參數 settings.pack_outlier，沿用包裝儀表板 v4）';

-- ── 5. 品項 × 月份 ───────────────────────────────────────────
create view production.sku_month with (security_invoker = true) as
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
j as (select * from m full join k using (sku_code, ym))
select j.sku_code, j.ym,
       coalesce((select s.name from packing.skus s where s.code = j.sku_code),
                (select max(r.sku_name) from production.runs r where r.sku_code = j.sku_code)) as sku_name,
       j.mfg_h, j.fill_h, j.fg_used, j.n_used, j.n_batch, j.n_closed, j.fg_all,
       j.pots, j.semi_est, j.semi_act, j.labour_h_all, j.labour_pots,
       j.pack_h, j.pack_b, j.n_pack, j.n_pack_outlier, j.pack_b_all, j.n_pack_all,
       case when j.fg_used > 0 and j.mfg_h  > 0 then round(j.mfg_h  / j.fg_used * 1000, 3) end as mfg_rate,
       case when j.fg_used > 0 and j.fill_h > 0 then round(j.fill_h / j.fg_used * 1000, 3) end as fill_rate,
       case when j.pack_b  > 0 and j.pack_h > 0 then round(j.pack_h / j.pack_b  * 1000, 3) end as pack_rate,
       case when j.semi_est > 0 then round(j.semi_act / j.semi_est * 100, 2) end as yield_pct,
       case when j.labour_pots > 0 then round(j.labour_h_all / j.labour_pots, 3) end as per_pot_h
from j;
comment on view production.sku_month is
  '品項 × 月份。mfg/fill/pack_rate＝人時/千瓶（製造充填除以結案成品數，包裝除以包裝瓶數，各用各的分母）；'
  'yield_pct＝製成率；per_pot_h＝每鍋人時（製造＋充填，非離群）';

-- ── 6. 每月門檻（納入標準計算的月份）──────────────────────────
create view production.month_gate with (security_invoker = true) as
with g as (select (value->>'fg_fill')::numeric as fg_fill, (value->>'head_pct')::numeric as head_pct,
                  (value->>'missing_days')::int as missing_days from production.settings where key = 'gate'),
b as (select value->>'from' as f, value->>'to' as t from production.settings where key = 'std_base'),
mc as (select ym, runs, fg_filled from production.month_counts),
ls as (select ym, invalid, o_mismatch from production.labour_status_by_month),
ms as (select ym, missing_days, head_pct, batches from packing.month_status)
select coalesce(mc.ym, ms.ym) as ym,
       case when mc.runs > 0 then round(100.0 * mc.fg_filled / mc.runs, 1) end as fg_fill_pct,
       ms.missing_days, ms.head_pct, ms.batches as pack_batches,
       ls.invalid as labour_invalid, ls.o_mismatch as labour_o_mismatch,
       coalesce(mc.runs > 0 and 100.0 * mc.fg_filled / mc.runs >= g.fg_fill, false) as gate_mfg,
       coalesce(ms.missing_days <= g.missing_days, false) as gate_pack,
       coalesce(ms.head_pct >= g.head_pct, false) as gate_head,
       coalesce(mc.runs > 0 and 100.0 * mc.fg_filled / mc.runs >= g.fg_fill
                and ms.missing_days <= g.missing_days and ms.head_pct >= g.head_pct, false) as gate,
       coalesce(mc.ym, ms.ym) between b.f and b.t as in_base
from mc full join ms using (ym) left join ls using (ym) cross join g cross join b;
comment on view production.month_gate is
  '每月三項門檻：製造結案率、包裝漏登天數、包裝人數填寫率（settings.gate）。gate＝三項都通過；in_base＝落在標準基準期';

-- ── 7. 品項標準（基準期中通過門檻月份的中位數）──────────────────
create view production.sku_std with (security_invoker = true) as
select s.sku_code,
       round((percentile_cont(0.5) within group (order by s.mfg_rate)  filter (where s.mfg_rate  is not null))::numeric, 3) as mfg_std,
       count(*) filter (where s.mfg_rate  is not null) as mfg_n,
       round((percentile_cont(0.5) within group (order by s.fill_rate) filter (where s.fill_rate is not null))::numeric, 3) as fill_std,
       count(*) filter (where s.fill_rate is not null) as fill_n,
       round((percentile_cont(0.5) within group (order by s.pack_rate) filter (where s.pack_rate is not null))::numeric, 3) as pack_std,
       count(*) filter (where s.pack_rate is not null) as pack_n
from production.sku_month s
join production.month_gate g on g.ym = s.ym and g.in_base and g.gate
group by s.sku_code;
comment on view production.sku_std is
  '品項標準：基準期（settings.std_base）內通過三項門檻的月份，各段人時/千瓶的中位數；*_n＝樣本月數（<3 僅供參考）';

-- ── 8. 品項 × 月份效率 ────────────────────────────────────────
-- 只比較「本月有實際、而且有標準」的工段；某段本月沒資料就不列入，避免把缺資料當成省人力。
create view production.sku_eff with (security_invoker = true) as
with x as (
  select s.sku_code, s.ym, s.sku_name, s.fg_used, s.pack_b,
         case when s.mfg_rate  is not null and t.mfg_std  is not null then s.mfg_h  end as mfg_h,
         case when s.mfg_rate  is not null and t.mfg_std  is not null then t.mfg_std  * s.fg_used / 1000 end as mfg_std_h,
         case when s.fill_rate is not null and t.fill_std is not null then s.fill_h end as fill_h,
         case when s.fill_rate is not null and t.fill_std is not null then t.fill_std * s.fg_used / 1000 end as fill_std_h,
         case when s.pack_rate is not null and t.pack_std is not null then s.pack_h end as pack_h,
         case when s.pack_rate is not null and t.pack_std is not null then t.pack_std * s.pack_b  / 1000 end as pack_std_h
  from production.sku_month s join production.sku_std t using (sku_code)
)
select x.*,
       coalesce(mfg_h, 0) + coalesce(fill_h, 0) + coalesce(pack_h, 0) as act_h,
       coalesce(mfg_std_h, 0) + coalesce(fill_std_h, 0) + coalesce(pack_std_h, 0) as std_h,
       round(((coalesce(mfg_std_h, 0) + coalesce(fill_std_h, 0) + coalesce(pack_std_h, 0))
              / nullif(coalesce(mfg_h, 0) + coalesce(fill_h, 0) + coalesce(pack_h, 0), 0) * 100)::numeric, 1) as ei,
       round((coalesce(mfg_h, 0) + coalesce(fill_h, 0) + coalesce(pack_h, 0)
              - coalesce(mfg_std_h, 0) - coalesce(fill_std_h, 0) - coalesce(pack_std_h, 0))::numeric, 2) as loss_h
from x
where coalesce(mfg_h, 0) + coalesce(fill_h, 0) + coalesce(pack_h, 0) > 0;
comment on view production.sku_eff is
  '品項 × 月份效率：std_h＝各段標準 × 該段產量；ei＝效率指數（std_h ÷ act_h × 100，>100 比標準快）；loss_h＝損失人時';

-- ── 9. 全廠月彙總 ────────────────────────────────────────────
create view production.plant_month with (security_invoker = true) as
select e.ym,
       count(*) as n_sku,
       round(sum(e.act_h)::numeric, 1) as act_h,
       round(sum(e.std_h)::numeric, 1) as std_h,
       round((sum(e.std_h) / nullif(sum(e.act_h), 0) * 100)::numeric, 1) as ei,
       round(sum(greatest(e.loss_h, 0))::numeric, 1) as loss_h,
       count(*) filter (where e.loss_h > 0) as n_loss_sku,
       round(sum(coalesce(e.mfg_h, 0))::numeric, 1)  as mfg_h,
       round(sum(coalesce(e.fill_h, 0))::numeric, 1) as fill_h,
       round(sum(coalesce(e.pack_h, 0))::numeric, 1) as pack_h,
       g.gate, g.fg_fill_pct
from production.sku_eff e left join production.month_gate g using (ym)
group by e.ym, g.gate, g.fg_fill_pct;
comment on view production.plant_month is
  '全廠每月：效率指數、全流程人時、損失人時（只加總比標準慢的品項）、各段人時、是否通過門檻';

-- ── 10. 生產批串接（2026/10 起包裝紀錄有製造日期）────────────────
create view production.batch_link with (security_invoker = true) as
with k as (
  select sku_code, mfg_date,
         sum(hours * headcount) as pack_h, sum(bottles) as pack_b, count(*) as n_pack,
         min(prod_date) as first_pack, max(prod_date) as last_pack,
         bool_or(outlier) as pack_outlier
  from production.pack_scored where mfg_date is not null
  group by 1, 2
)
select k.*, (k.first_pack - k.mfg_date) as lag_days,
       m.sku_code is not null as matched,
       m.sku_name, m.pots, m.fg, m.closed, m.mfg_h, m.fill_h, m.outlier as mfg_outlier, m.labour_bad
from k left join production.mfg_batch m on m.sku_code = k.sku_code and m.prod_date = k.mfg_date;
comment on view production.batch_link is
  '以（料號, 製造日期）把包裝接到製造批。lag_days＝製造到第一次包裝的天數；matched＝製成率資料找得到這一批';

-- ── 11. 物料平衡（近 3 個月包裝瓶數 ÷ 製造成品數）──────────────
create view production.balance_check with (security_invoker = true) as
with p as (select (value->>'lo')::numeric as lo, (value->>'hi')::numeric as hi from production.settings where key = 'balance'),
s as (
  select sku_code, ym, to_date(ym || '-01', 'YYYY-MM-DD') as md,
         coalesce(fg_all, 0) as fg, coalesce(pack_b_all, 0) as pb
  from production.sku_month
),
w as (
  select sku_code, ym,
         sum(fg) over (partition by sku_code order by md range between interval '2 months' preceding and current row) as fg3,
         sum(pb) over (partition by sku_code order by md range between interval '2 months' preceding and current row) as pb3
  from s
)
select w.sku_code, w.ym, w.fg3, w.pb3,
       case when w.fg3 > 0 then round(w.pb3 / w.fg3, 3) end as ratio,
       (coalesce(g.gate_mfg, false) and w.fg3 > 0 and w.pb3 > 0 and w.fg3 + w.pb3 >= 600
        and (w.pb3 / w.fg3 < p.lo or w.pb3 / w.fg3 > p.hi)) as flagged,
       coalesce(g.gate_mfg, false) as fg_ready
from w cross join p left join production.month_gate g on g.ym = w.ym;
comment on view production.balance_check is
  '物料平衡：近 3 個月包裝瓶數 ÷ 製造成品數；fg_ready＝該月成品數已填齊（未填齊的月份不標記）；flagged＝超出 settings.balance 範圍（只列清單，不擋月份）';

-- ── 12. 工時待處理清單 ─────────────────────────────────────────
create view production.labour_issues with (security_invoker = true) as
select c.prod_date, to_char(c.prod_date, 'YYYY-MM') as ym, c.sku_code, c.sku_name, c.src_row,
       'invalid'::text as kind, c.reason as detail
from production.labour_check c
where c.status = 'invalid' and not exists (select 1 from production.labour_run r where r.id = c.id)
union all
select c.prod_date, to_char(c.prod_date, 'YYYY-MM'), c.sku_code, c.sku_name, c.src_row, 'o_note', c.o_note
from production.labour_check c
where c.o_note is not null;
comment on view production.labour_issues is
  '工時待處理：invalid＝不納入計算，需回 Excel 修正；o_note＝Excel O 欄可能打錯（僅提醒）。src_row 是 Excel 列號';

grant select on production.labour_run, production.labour_scored, production.mfg_batch, production.pack_scored,
  production.sku_month, production.month_gate, production.sku_std, production.sku_eff, production.plant_month,
  production.batch_link, production.balance_check, production.labour_issues
  to authenticated, service_role;
