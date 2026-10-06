-- 午休扣法更正（2026-10-06 Jackie 哥確認）：
--
--   ‧ 生產時段「完整涵蓋」12:00–13:00 → 扣 60 分
--   ‧ 12 點多才開工（提早用餐、提早上工）→ 不扣，從開工時間照實計入
--   ‧ 做到 12 點多才結束（延後用餐）→ 不扣，照實計入
--
-- 這與 Excel O 欄的公式一致。原本「扣實際重疊」的寫法會把 12:30 開工的人少算 30 分，
-- 實測 51 列「自算 ≠ O 欄」中 48 列就是這個原因；其餘 2,376 列有效資料不受影響。
--
-- 本檔一併包含 20261006120000（人時依起訖計算、O 欄只作提醒）的內容：
-- 若那一份還沒執行，執行這一份即可；已執行過也可以重複執行。
--
-- 【套用方式】在 Supabase 後台 SQL Editor 執行。整份在同一個交易內，失敗會全部還原。

begin;

create or replace function production.stage_min(p_start time, p_end time, p_prep smallint)
returns numeric
language sql immutable
set search_path = ''
as $$
  select case
    when p_start is null or p_end is null or p_end <= p_start then null
    else round(extract(epoch from (p_end - p_start)) / 60.0
               - case when p_start <= time '12:00' and p_end >= time '13:00' then 60 else 0 end
               + coalesce(p_prep, 0), 2)
  end
$$;
comment on function production.stage_min is
  '工段分鐘：（結束−開始）＋前置；完整涵蓋 12:00–13:00 才扣 60 分（12 點多開工或做到 12 點多都照實計入）。結束≤開始回傳 null';

-- 已存的分鐘數依新公式全部重算
alter table production.labour alter column mfg_min  set expression as (production.stage_min(mfg_start,  mfg_end,  mfg_prep_min));
alter table production.labour alter column fill_min set expression as (production.stage_min(fill_start, fill_end, fill_prep_min));

create or replace view production.labour_check with (security_invoker = true) as
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
), t as (
  select s.*,
    case when mfg_state  = 'ok' then round(mfg_min  * mfg_people,  1) end as mpm,
    case when fill_state = 'ok' then round(fill_min * fill_people, 1) end as fpm
  from s
)
select t.id, t.prod_date, t.sku_code, t.seq, t.sku_name, t.pots,
  t.mfg_min, t.fill_min,
  t.mpm as mfg_person_min,
  t.fpm as fill_person_min,
  t.listed_person_min,
  case
    when t.mfg_state = 'empty' and t.fill_state = 'empty' then 'empty'
    when t.mfg_state not in ('ok', 'empty') or t.fill_state not in ('ok', 'empty') then 'invalid'
    else 'ok'
  end as status,
  case
    when t.mfg_state = 'empty' and t.fill_state = 'empty' then '兩段皆未填（非人工列）'
    when t.mfg_state not in ('ok', 'empty') or t.fill_state not in ('ok', 'empty') then
      concat_ws('、',
        case t.mfg_state  when 'bad_time' then '製造段缺／異常生產時間'
                          when 'bad_people' then '製造段缺人數' when 'bad_zero' then '製造段生產時間為 0' end,
        case t.fill_state when 'bad_time' then '充填段缺／異常生產時間'
                          when 'bad_people' then '充填段缺人數' when 'bad_zero' then '充填段生產時間為 0' end)
  end as reason,
  t.src_row,
  coalesce(t.mpm, 0) + coalesce(t.fpm, 0) as person_min,
  (t.mfg_state = 'ok') <> (t.fill_state = 'ok') as single_stage,
  case when t.mfg_state in ('ok', 'empty') and t.fill_state in ('ok', 'empty')
        and not (t.mfg_state = 'empty' and t.fill_state = 'empty')
        and t.listed_person_min is not null
        and abs(coalesce(t.mpm, 0) + coalesce(t.fpm, 0) - t.listed_person_min) > 1
       then format('系統依起訖計算 %s 人·分，Excel O 欄為 %s（Excel 可能打錯，以系統為準）',
                   round(coalesce(t.mpm, 0) + coalesce(t.fpm, 0)), round(t.listed_person_min))
  end as o_note
from t;
comment on view production.labour_check is
  '工時逐列檢核。人時一律依填入的起訖、前置、人數計算（完整涵蓋 12:00–13:00 才扣 60 分），O 欄只作參考。'
  'status：ok＝納入計算（含只填一段）；invalid＝時間或人數缺漏／顛倒（reason 說明）；empty＝非人工列。'
  'o_note：系統計算與 Excel O 欄不同時的提醒，不影響計算';

create or replace view production.labour_status_by_month with (security_invoker = true) as
select to_char(prod_date, 'YYYY-MM') as ym,
       count(*) filter (where status = 'ok')      as ok,
       count(*) filter (where status = 'invalid') as invalid,
       count(*) filter (where status = 'empty')   as empty,
       count(*) filter (where o_note is not null) as o_mismatch,
       count(*) filter (where status = 'ok' and single_stage) as single_stage
from production.labour_check
group by 1;
comment on view production.labour_status_by_month is
  '各月工時列的檢核結果：ok 納入計算、invalid 需回 Excel 修正、empty 非人工列；o_mismatch＝O 欄與系統不同（僅提醒）';
grant select on production.labour_status_by_month to authenticated, service_role;

commit;

-- 驗收：12:30 開工不扣、完整涵蓋扣 60、做到 12:10 不扣；以及全期與近 3 個月的檢核結果
select
  production.stage_min('12:30', '16:00', null) = 210 as "12:30開工不扣 ✔",
  production.stage_min('07:00', '16:00', null) = 480 as "涵蓋午休扣60 ✔",
  production.stage_min('09:00', '14:00', null) = 240 as "09:00–14:00扣60 ✔",
  production.stage_min('07:00', '12:10', null) = 310 as "做到12:10不扣 ✔",
  (select count(*) from production.labour_check where o_note is not null) as "全期O欄不同（應約3）",
  (select string_agg(ym || '：有效' || ok || '／異常' || invalid, '，' order by ym)
     from production.labour_status_by_month where ym >= '2026-07') as "近3個月";
