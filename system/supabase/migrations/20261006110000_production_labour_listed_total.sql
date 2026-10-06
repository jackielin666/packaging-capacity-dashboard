-- 工時分頁加存 R 欄「總生產時間(分)」，並提供各月工時檢核統計。
--
-- 製成率系統的「總生產時間／每鍋工時」是直接加總 R 欄，不是由起訖推算；
-- 要做到兩邊數字一致，就得把這一欄也存下來。它只供核對與對照，
-- 本系統的人時一律由起訖、前置、人數推算。

alter table production.labour add column if not exists listed_total_min numeric(10,1);
comment on column production.labour.listed_total_min is 'Excel R 欄「總生產時間(分)」。製成率系統的「總生產時間／每鍋工時」用這一欄，保留以便兩邊數字一致';

create or replace view production.labour_status_by_month with (security_invoker = true) as
select to_char(prod_date, 'YYYY-MM') as ym,
       count(*) filter (where status = 'ok')      as ok,
       count(*) filter (where status = 'invalid') as invalid,
       count(*) filter (where status = 'empty')   as empty
from production.labour_check
group by 1;
comment on view production.labour_status_by_month is '各月工時列的檢核結果：ok 納入計算、invalid 需回 Excel 修正、empty 非人工列';
grant select on production.labour_status_by_month to authenticated, service_role;

-- 匯入函式改為一併寫入 listed_total_min（其餘與前一版相同）
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
     listed_person_min, listed_total_min, src_row, import_id)
  select l.prod_date, l.sku_code, l.seq, l.sku_name, l.pots,
         l.mfg_people, l.mfg_prep_min, l.mfg_start, l.mfg_end,
         l.fill_people, l.fill_prep_min, l.fill_start, l.fill_end,
         l.listed_person_min, l.listed_total_min, l.src_row, v_id
  from jsonb_to_recordset(coalesce(p_labour, '[]'::jsonb)) as l(
    prod_date date, sku_code text, seq smallint, sku_name text, pots numeric,
    mfg_people numeric, mfg_prep_min smallint, mfg_start time, mfg_end time,
    fill_people numeric, fill_prep_min smallint, fill_start time, fill_end time,
    listed_person_min numeric, listed_total_min numeric, src_row integer);
  get diagnostics n_lab = row_count;

  update production.imports set runs_rows = n_runs, labour_rows = n_lab where id = v_id;

  return jsonb_build_object('import_id', v_id, 'runs', n_runs, 'labour', n_lab,
    'runs_deleted', v_clear->'runs_deleted', 'labour_deleted', v_clear->'labour_deleted');
end $$;
