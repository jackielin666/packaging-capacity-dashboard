-- 品項全流程工時成本：製造／充填資料（來自製成率 Excel），獨立 schema。
--
-- 原則（與 packing 相同）：
--   ‧ Excel 是唯一來源。這裡忠實保存兩張分頁的原始欄位，不做判斷；
--     哪些列算有效、怎麼算人時，交給下面的 view，規則改了不必重新匯入。
--   ‧ 工段分鐘是「算出來的」，不是填進去的：只存起訖、前置、人數。
--   ‧ 匯入以「月」為單位整月覆蓋，同一份 Excel 匯入兩次結果不變。
--   ‧ 讀：所有成員；寫：只有主管（匯入由 admin000／admin001 執行）。
--     角色沿用 packing.members，不另外管帳號。

create schema if not exists production;
comment on schema production is '品項全流程工時成本：製成率 Excel 的資料總表與工時分頁';

-- ── 匯入紀錄：誰、何時、哪個檔、覆蓋了哪些月份 ──────────────────
create table production.imports (
  id           bigint generated always as identity primary key,
  file_name    text not null,
  months       text[] not null,
  runs_rows    integer not null default 0,
  labour_rows  integer not null default 0,
  note         text,
  imported_by  uuid references auth.users(id) default auth.uid(),
  imported_at  timestamptz not null default now()
);
comment on column production.imports.months is '這次覆蓋的月份（YYYY-MM）。資料齊全度用它判斷「製造資料已匯入」';

-- ── 資料總表（每日每品項的產出）────────────────────────────────
create table production.runs (
  id         bigint generated always as identity primary key,
  prod_date  date not null,
  sku_code   text not null,
  seq        smallint not null default 1 check (seq >= 1),
  sku_name   text,
  pots       numeric(8,2),
  spec_kg    numeric(9,3),
  semi_est   numeric(11,2),
  semi_act   numeric(11,2),
  semi_kg    numeric(11,2),
  fg_act     integer,
  defects    integer,
  note       text,
  src_row    integer,
  import_id  bigint references production.imports(id) on delete set null,
  unique (sku_code, prod_date, seq)
);
comment on table  production.runs is '製成率 Excel「資料總表」。一列＝某日某品項的一次生產';
comment on column production.runs.seq      is '同一天同一料號出現多列時的序號（依 Excel 列順序）';
comment on column production.runs.semi_est is '半成品數（預估）';
comment on column production.runs.semi_act is '半成品數（實際）。製成率 = semi_act ÷ semi_est';
comment on column production.runs.fg_act   is '成品數（實際）。製造／充填人時的分母；空白＝尚未結案';
comment on column production.runs.src_row  is 'Excel 列號，方便回頭查原始資料';
create index runs_date_idx on production.runs (prod_date);

-- ── 工時（製造段＋充填段）──────────────────────────────────────
-- 工段分鐘 =（結束 − 開始）− 與 12:00–13:00 午休重疊 + 前置。
-- 規則與製成率系統（yield-worktime-stats）的 classifyStage 相同；
-- 結束 ≤ 開始視為資料異常（回傳 null），不猜跨午夜。
create or replace function production.stage_min(p_start time, p_end time, p_prep smallint)
returns numeric
language sql immutable
set search_path = ''
as $$
  select case
    when p_start is null or p_end is null or p_end <= p_start then null
    else round((extract(epoch from (p_end - p_start))
              - greatest(0, extract(epoch from (least(p_end, time '13:00') - greatest(p_start, time '12:00'))))
               ) / 60.0 + coalesce(p_prep, 0), 2)
  end
$$;
comment on function production.stage_min is '工段分鐘：（結束−開始）−午休重疊＋前置。結束≤開始回傳 null';

create table production.labour (
  id                 bigint generated always as identity primary key,
  prod_date          date not null,
  sku_code           text not null,
  seq                smallint not null default 1 check (seq >= 1),
  sku_name           text,
  pots               numeric(8,2),
  mfg_people         numeric(5,1),
  mfg_prep_min       smallint,
  mfg_start          time,
  mfg_end            time,
  fill_people        numeric(5,1),
  fill_prep_min      smallint,
  fill_start         time,
  fill_end           time,
  listed_person_min  numeric(10,1),
  mfg_min   numeric generated always as (production.stage_min(mfg_start,  mfg_end,  mfg_prep_min))  stored,
  fill_min  numeric generated always as (production.stage_min(fill_start, fill_end, fill_prep_min)) stored,
  src_row    integer,
  import_id  bigint references production.imports(id) on delete set null,
  unique (sku_code, prod_date, seq)
);
comment on table  production.labour is '製成率 Excel「工時」分頁。製造段與充填段各自的人數、前置、起訖';
comment on column production.labour.listed_person_min is 'Excel O 欄「生產時間*人數」。只用來核對自算結果，不參與計算';
comment on column production.labour.mfg_min  is '製造段分鐘（自動推算）';
comment on column production.labour.fill_min is '充填段分鐘（自動推算）';
create index labour_date_idx on production.labour (prod_date);

-- ── 參數 ────────────────────────────────────────────────────
-- 工時費率刻意不放這裡：它是畫面上的試算欄位，不存檔。
create table production.settings (
  key        text primary key,
  value      jsonb not null,
  note       text,
  updated_at timestamptz not null default now()
);
insert into production.settings (key, value, note) values
  ('std_base',    '{"from": "2026-03", "to": "2026-08"}', '標準工時的基準期（每半年檢討）'),
  ('ei_level',    '{"warn": 95, "crit": 85}',             '效率指數燈號：≥warn 正常、crit–warn 注意、<crit 異常'),
  ('outlier',     '{"min_n": 8, "mz": 3.5, "dev": 0.35, "cap": 0.10}', '離群批次判定（沿用製成率系統）'),
  ('balance',     '{"lo": 0.85, "hi": 1.15, "months": 3}', '物料平衡檢視範圍（只列清單，不擋月份）'),
  ('gate',        '{"fg_fill": 95, "head_pct": 95, "missing_days": 0}', '納入標準計算的三項門檻'),
  ('lag_days',    '{"late": 7}',                           '製造→包裝超過幾天算延遲');

-- ── 工時逐列檢核：哪些列有效、無效的原因 ─────────────────────────
-- 與製成率系統相同：兩段都完整、且自算人時與 O 欄差 ≤ 1 分，才算有效。
create view production.labour_check with (security_invoker = true) as
with s as (
  select l.*,
    case when mfg_start is null and mfg_end is null and coalesce(mfg_people, 0) = 0 then 'empty'
         when mfg_min is null then 'bad_time'
         when coalesce(mfg_people, 0) <= 0 then 'bad_people'
         when mfg_min <= 0 then 'bad_zero' else 'ok' end as mfg_state,
    case when fill_start is null and fill_end is null and coalesce(fill_people, 0) = 0 then 'empty'
         when fill_min is null then 'bad_time'
         when coalesce(fill_people, 0) <= 0 then 'bad_people'
         when fill_min <= 0 then 'bad_zero' else 'ok' end as fill_state
  from production.labour l
)
select s.id, s.prod_date, s.sku_code, s.seq, s.sku_name, s.pots,
  s.mfg_min, s.fill_min,
  case when s.mfg_state  = 'ok' then round(s.mfg_min  * s.mfg_people,  1) end as mfg_person_min,
  case when s.fill_state = 'ok' then round(s.fill_min * s.fill_people, 1) end as fill_person_min,
  s.listed_person_min,
  case
    when s.mfg_state = 'empty' and s.fill_state = 'empty' then 'empty'
    when s.mfg_state <> 'ok' or s.fill_state <> 'ok' then 'invalid'
    when s.listed_person_min is null then 'invalid'
    when abs(s.mfg_min * s.mfg_people + s.fill_min * s.fill_people - s.listed_person_min) > 1 then 'invalid'
    else 'ok'
  end as status,
  case
    when s.mfg_state = 'empty' and s.fill_state = 'empty' then '兩段皆未填（非人工列）'
    when s.mfg_state <> 'ok' or s.fill_state <> 'ok' then
      concat_ws('、',
        case s.mfg_state  when 'empty' then '製造段未填' when 'bad_time' then '製造段缺／異常生產時間'
                          when 'bad_people' then '製造段缺人數' when 'bad_zero' then '製造段生產時間為 0' end,
        case s.fill_state when 'empty' then '充填段未填' when 'bad_time' then '充填段缺／異常生產時間'
                          when 'bad_people' then '充填段缺人數' when 'bad_zero' then '充填段生產時間為 0' end)
    when s.listed_person_min is null then '缺「生產時間×人數」欄，無法核對'
    when abs(s.mfg_min * s.mfg_people + s.fill_min * s.fill_people - s.listed_person_min) > 1 then
      format('自算 %s 人·分 ≠ 表列 %s', round(s.mfg_min * s.mfg_people + s.fill_min * s.fill_people), round(s.listed_person_min))
  end as reason,
  s.src_row
from s;
comment on view production.labour_check is
  '工時逐列檢核。status：ok＝納入計算；invalid＝資料不全或與 O 欄不符（reason 說明）；empty＝非人工列';

-- ── 權限 ────────────────────────────────────────────────────
alter table production.imports  enable row level security;
alter table production.runs     enable row level security;
alter table production.labour   enable row level security;
alter table production.settings enable row level security;

create policy imports_read  on production.imports  for select to authenticated using (packing.my_role() is not null);
create policy runs_read     on production.runs     for select to authenticated using (packing.my_role() is not null);
create policy labour_read   on production.labour   for select to authenticated using (packing.my_role() is not null);
create policy settings_read on production.settings for select to authenticated using (packing.my_role() is not null);

create policy imports_write  on production.imports  for all to authenticated
  using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');
create policy runs_write     on production.runs     for all to authenticated
  using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');
create policy labour_write   on production.labour   for all to authenticated
  using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');
create policy settings_write on production.settings for all to authenticated
  using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');

-- 刻意不授權給 anon：未登入的人讀不到任何資料。
grant usage on schema production to authenticated, service_role;
grant select on all tables in schema production to authenticated;
grant insert, update, delete on production.imports, production.runs, production.labour, production.settings to authenticated;
grant usage, select on all sequences in schema production to authenticated;
grant all on all tables in schema production to service_role;
grant all on all sequences in schema production to service_role;
revoke all on function production.stage_min(time, time, smallint) from public, anon;
grant execute on function production.stage_min(time, time, smallint) to authenticated, service_role;
