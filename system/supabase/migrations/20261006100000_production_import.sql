-- 製成率 Excel 匯入：以「月」為單位整月覆蓋，一次呼叫就是一個交易。
--
-- 為什麼在資料庫裡做：刪舊、寫新、記錄三件事要嘛全成功、要嘛全不動。
-- 若在網頁上分三次呼叫，中途斷線就會留下「舊的刪了、新的沒寫」的空月份。
--
-- 防呆：
--   ‧ 只有主管能呼叫（與 RLS 同一個判斷，這裡先擋，訊息比較好懂）
--   ‧ 每一列的日期都必須落在這次指定的月份內 —— 網頁端算錯月份時，
--     不會因此刪掉沒打算動的月份
--   ‧ security invoker：照呼叫者的權限執行，RLS 仍然有效
--
-- 【套用方式】這份要在 Supabase 後台的 SQL Editor 執行。
-- 管理工具（MCP）送出含 DELETE、DROP 的函式定義時會逾時，與 packing 遇到的情況相同。

-- 各月目前有幾列，匯入前的差異預覽用（已由管理工具套用，這裡保留完整定義）
create or replace view production.month_counts with (security_invoker = true) as
select ym,
       sum(runs)::int      as runs,
       sum(fg_filled)::int as fg_filled,
       sum(labour)::int    as labour
from (
  select to_char(prod_date, 'YYYY-MM') as ym, count(*) as runs, count(fg_act) as fg_filled, 0 as labour
  from production.runs group by 1
  union all
  select to_char(prod_date, 'YYYY-MM'), 0, 0, count(*)
  from production.labour group by 1
) t
group by ym;
comment on view production.month_counts is '各月資料總表／工時列數，與成品數已填列數（結案率）';

-- 清除指定月份（只給 import_months 在同一交易內呼叫）
create or replace function production.clear_months(p_months text[])
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare d_runs int; d_lab int;
begin
  if packing.my_role() is distinct from 'manager' then
    raise exception '只有主管帳號可以清除月份資料' using errcode = '42501';
  end if;
  delete from production.runs   where to_char(prod_date, 'YYYY-MM') = any (p_months);
  get diagnostics d_runs = row_count;
  delete from production.labour where to_char(prod_date, 'YYYY-MM') = any (p_months);
  get diagnostics d_lab = row_count;
  return jsonb_build_object('runs_deleted', d_runs, 'labour_deleted', d_lab);
end $$;

create or replace function production.import_months(
  p_file   text,
  p_months text[],
  p_runs   jsonb,
  p_labour jsonb
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_id    bigint;
  v_clear jsonb;
  n_runs  int; n_lab int;
begin
  if packing.my_role() is distinct from 'manager' then
    raise exception '只有主管帳號可以匯入製成率資料' using errcode = '42501';
  end if;
  if p_months is null or cardinality(p_months) = 0 then
    raise exception '沒有指定要匯入的月份';
  end if;
  if exists (select 1 from jsonb_array_elements(coalesce(p_runs, '[]'::jsonb)) e
             where left(e->>'prod_date', 7) <> all (p_months))
  or exists (select 1 from jsonb_array_elements(coalesce(p_labour, '[]'::jsonb)) e
             where left(e->>'prod_date', 7) <> all (p_months)) then
    raise exception '有資料列的日期不在這次匯入的月份內，已全部取消';
  end if;

  insert into production.imports (file_name, months) values (p_file, p_months) returning id into v_id;
  v_clear := production.clear_months(p_months);

  insert into production.runs
    (prod_date, sku_code, seq, sku_name, pots, spec_kg, semi_est, semi_act, semi_kg, fg_act, defects, note, src_row, import_id)
  select r.prod_date, r.sku_code, r.seq, r.sku_name, r.pots, r.spec_kg, r.semi_est, r.semi_act, r.semi_kg,
         r.fg_act, r.defects, r.note, r.src_row, v_id
  from jsonb_to_recordset(coalesce(p_runs, '[]'::jsonb)) as r(
    prod_date date, sku_code text, seq smallint, sku_name text, pots numeric, spec_kg numeric,
    semi_est numeric, semi_act numeric, semi_kg numeric, fg_act integer, defects integer, note text, src_row integer);
  get diagnostics n_runs = row_count;

  insert into production.labour
    (prod_date, sku_code, seq, sku_name, pots,
     mfg_people, mfg_prep_min, mfg_start, mfg_end,
     fill_people, fill_prep_min, fill_start, fill_end,
     listed_person_min, src_row, import_id)
  select l.prod_date, l.sku_code, l.seq, l.sku_name, l.pots,
         l.mfg_people, l.mfg_prep_min, l.mfg_start, l.mfg_end,
         l.fill_people, l.fill_prep_min, l.fill_start, l.fill_end,
         l.listed_person_min, l.src_row, v_id
  from jsonb_to_recordset(coalesce(p_labour, '[]'::jsonb)) as l(
    prod_date date, sku_code text, seq smallint, sku_name text, pots numeric,
    mfg_people numeric, mfg_prep_min smallint, mfg_start time, mfg_end time,
    fill_people numeric, fill_prep_min smallint, fill_start time, fill_end time,
    listed_person_min numeric, src_row integer);
  get diagnostics n_lab = row_count;

  update production.imports set runs_rows = n_runs, labour_rows = n_lab where id = v_id;

  return jsonb_build_object('import_id', v_id, 'runs', n_runs, 'labour', n_lab,
    'runs_deleted', v_clear->'runs_deleted', 'labour_deleted', v_clear->'labour_deleted');
end $$;
comment on function production.import_months is
  '整月覆蓋匯入。p_months 內的月份先刪後寫，同一交易；只有主管可呼叫';

revoke all on function production.clear_months(text[]) from public, anon;
grant execute on function production.clear_months(text[]) to authenticated, service_role;
revoke all on function production.import_months(text, text[], jsonb, jsonb) from public, anon;
grant execute on function production.import_months(text, text[], jsonb, jsonb) to authenticated, service_role;
grant select on production.month_counts, production.labour_check to authenticated, service_role;

-- 清掉 2026-10-06 排查管理工具逾時時留下的測試函式（已改成無作用、無人可呼叫）
drop function if exists production._probe(jsonb);
drop function if exists production._probe(integer);
drop function if exists production._probe2(jsonb);
drop function if exists production._probe3(bigint);

-- 執行完應該看到一列：import_months ✔、clear_months ✔、測試函式 0
select
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'production' and p.proname = 'import_months') = 1 as "import_months ✔",
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'production' and p.proname = 'clear_months') = 1  as "clear_months ✔",
  (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'production' and p.proname like '\_probe%') as "測試函式（應為 0）";
