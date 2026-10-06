-- 人時一律依填入的起訖時間計算，O 欄只作參考（2026-10-06 Jackie 哥決定）。
--
-- 背景：實測 51 列「自算 ≠ O 欄」，其中 48 列是 Excel O 欄的公式在
-- 「生產時間部分跨到午休」時沒有扣掉重疊（例如 12:30 開始只該扣 30 分，O 欄沒扣）。
-- 午休 12:00–13:00，只要跨到就扣實際重疊的時間 —— 這正是 stage_min 的算法，公式不變。
--
-- 改變的是判定：
--   ‧「自算 ≠ O 欄」不再算異常，改為 o_note 提醒（Excel 公式可能有誤，以系統為準）
--   ‧ 只填一段（另一段完全空白）視為有效，人時＝有填的那一段
--   ‧ 異常（invalid）只剩真正的資料問題：時間或人數缺漏、結束早於開始、時間為 0
--
-- 影響：製成率不變；人時會與製成率系統不同（它把上述列當異常排除），以本系統為準。
--
-- 【套用方式】在 Supabase 後台 SQL Editor 執行（本檔沒有刪除指令，管理工具也可套用）。

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
       then format('系統依起訖計算 %s 人·分，Excel O 欄為 %s（Excel 公式可能有誤，以系統為準）',
                   round(coalesce(t.mpm, 0) + coalesce(t.fpm, 0)), round(t.listed_person_min))
  end as o_note
from t;
comment on view production.labour_check is
  '工時逐列檢核。人時一律依填入的起訖、前置、人數計算（午休 12:00–13:00 扣實際重疊），O 欄只作參考。'
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

-- 執行完應看到最近 3 個月的結果（invalid 應明顯減少）
select ym as 月份, ok as 有效, invalid as 異常, o_mismatch as "O欄不同（僅提醒）", single_stage as 只填一段
from production.labour_status_by_month
where ym >= '2026-07' order by ym;
