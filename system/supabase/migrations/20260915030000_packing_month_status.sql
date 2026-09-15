-- 月度完整性檢核用的彙總。一個檢視同時回答兩件事：
--   1. 每個月有幾個工作日「該登記卻沒登記」
--   2. 人數補登到哪裡了（階段 4 人均效率分析的前提）
--
-- 工作日只算週一到週五。國定假日不內建（每年不同），現場用
-- 「本日無包裝作業」標記，有標記的日子不算漏登。
--
-- is_imported 是關鍵：匯入的歷史來自 Excel，而 Excel 裡沒有「那天沒生產」
-- 這種紀錄，空白的日子無從判斷究竟是沒做還是漏記。整個歷史區間有 23 個
-- 這種日子，當成待辦丟給現場就是 23 件查不出答案的假工作 —— 清單一旦混進
-- 查不到答案的項目，整份就會被放棄，連真的漏登也一起被忽略。
-- 所以檢核只對系統上線後的月份負責。
create view packing.month_status with (security_invoker = true) as
with months as (
  select generate_series(
           coalesce((select date_trunc('month', min(prod_date)) from packing.batches),
                    date_trunc('month', packing.today_tw())),
           date_trunc('month', packing.today_tw()),
           interval '1 month')::date as m
),
days as (
  select months.m, g::date as d
  from months
  cross join lateral generate_series(
      months.m,
      (months.m + interval '1 month' - interval '1 day')::date,
      interval '1 day') g
  where g::date <= packing.today_tw()          -- 未來的日子不算漏登
),
daycnt as (
  select days.m,
    count(*) filter (where extract(isodow from days.d) <= 5)                     as workdays,
    count(*) filter (where extract(isodow from days.d) <= 5
                       and coalesce(s.batches, 0) > 0)                           as logged_days,
    count(*) filter (where extract(isodow from days.d) <= 5
                       and coalesce(s.batches, 0) = 0
                       and coalesce(s.no_operation, false))                      as no_op_days,
    count(*) filter (where extract(isodow from days.d) <= 5
                       and coalesce(s.batches, 0) = 0
                       and not coalesce(s.no_operation, false))                  as blank_days
  from days
  left join packing.day_summary s on s.prod_date = days.d
  group by days.m
),
batchcnt as (
  select date_trunc('month', prod_date)::date as m,
         count(*)                                    as batches,
         sum(bottles)                                as bottles,
         sum(hours)                                  as hours,
         count(headcount)                            as with_headcount,
         count(*) filter (where source = 'import')   as imported
  from packing.batches
  group by 1
)
select to_char(d.m, 'YYYY-MM')                      as ym,
       d.m                                          as month_start,
       coalesce(b.imported, 0) > 0                  as is_imported,
       d.workdays,
       d.logged_days,
       d.no_op_days,
       d.blank_days,
       case when coalesce(b.imported, 0) > 0 then 0 else d.blank_days end
                                                    as missing_days,
       coalesce(b.batches, 0)                       as batches,
       coalesce(b.bottles, 0)                       as bottles,
       coalesce(b.hours, 0)                         as hours,
       coalesce(b.with_headcount, 0)                as with_headcount,
       case when coalesce(b.batches, 0) > 0
            then round(100.0 * b.with_headcount / b.batches)
       end                                          as head_pct
from daycnt d
left join batchcnt b on b.m = d.m;

comment on view packing.month_status is
  '每月的登記完整性與人數補登進度。missing_days 只對系統上線後的月份有意義；'
  '匯入的歷史月份（is_imported）沒有「當天沒生產」的紀錄可比對，空白日不列入待補。';

grant select on packing.month_status to authenticated, service_role;
