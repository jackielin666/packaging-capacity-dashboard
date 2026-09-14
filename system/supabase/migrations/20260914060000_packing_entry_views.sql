-- 輸入介面要即時回答兩個問題，各給一個檢視，避免前端把整張表拉下來自己算。
--
-- security_invoker = true：檢視用「呼叫者」的身分讀底層資料表，
-- 所以 RLS 照樣生效，不會因為包一層檢視就繞過權限。

-- ── 1. 每個品項的歷史水準 ────────────────────────────────
-- 用途：輸入當下判斷「這批產能是不是離群」。
-- 門檻沿用儀表板的定義（平均 ×0.7 ／ ×2.5），兩邊才不會各說各話。
create view packing.sku_stats with (security_invoker = true) as
select
  s.code,
  s.name,
  s.container,
  s.unit_weight_kg,
  s.units_per_record,
  s.active,
  count(b.id)                                            as batches,
  coalesce(sum(b.bottles), 0)                            as bottles,
  coalesce(sum(b.hours), 0)                              as hours,
  case when sum(b.hours) > 0
       then round(sum(b.bottles) / sum(b.hours))
  end                                                    as mean_rate,
  case when count(b.id) > 0
       then round(percentile_cont(0.5) within group (
              order by (b.bottles / b.hours)::double precision)::numeric)
  end                                                    as median_rate,
  max(b.prod_date)                                       as last_date
from packing.skus s
left join packing.batches b on b.sku_code = s.code
group by s.code, s.name, s.container, s.unit_weight_kg, s.units_per_record, s.active;

comment on view packing.sku_stats is
  '每個品項的歷史產能水準。mean_rate 供離群門檻使用（×0.7 偏低、×2.5 偏高）。';


-- ── 2. 每個日期的登記狀況 ────────────────────────────────
-- 用途：月曆上一眼看出哪幾天已登、哪幾天標了無作業、哪幾天還沒處理。
-- 用 full outer join 是因為「有批次」與「標記無作業」是兩個獨立來源，
-- 任一邊有資料，那天就算已經處理過。
create view packing.day_summary with (security_invoker = true) as
select
  coalesce(b.prod_date, s.prod_date)      as prod_date,
  coalesce(b.batches, 0)                  as batches,
  coalesce(b.bottles, 0)                  as bottles,
  coalesce(b.hours, 0)                    as hours,
  coalesce(s.no_operation, false)         as no_operation,
  s.note                                  as day_note
from (
  select prod_date, count(*) as batches, sum(bottles) as bottles, sum(hours) as hours
  from packing.batches
  group by prod_date
) b
full outer join packing.daily_status s on s.prod_date = b.prod_date;

comment on view packing.day_summary is
  '每日登記狀況。batches = 0 且 no_operation = false 的工作日即為漏登。';

grant select on packing.sku_stats, packing.day_summary to authenticated, service_role;
