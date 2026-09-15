-- 人均產能的基礎。
--
-- 兩個指標要分清楚，它們回答不同的問題：
--   線體產能 = 產出 ÷ 工時        → 這條線跑多快
--   人均產能 = 產出 ÷ (工時×人數) → 每個人每小時做出多少
--
-- 同樣的線體產能，用 3 個人和用 6 個人做出來，人力成本差一倍。
-- 只看線體產能看不出這件事。
--
-- 覆蓋率是這裡最關鍵的欄位：人數是慢慢補登的，只有部分批次有。
-- 拿「有人數的那幾批」去代表整支品項會有選擇偏誤 ——
-- 所以每個數字都必須附上它涵蓋了多少批，讓讀的人自己判斷能信多少。

-- ── 為什麼人均要看兩個數字 ────────────────────────────────
--
--   單位/人·hr = 每個人每小時處理幾件 → 作業強度（手做了幾次）
--   kg/人·hr   = 每個人每小時產出多重 → 產出價值（搬了多少貨）
--
-- 兩者相差的倍數，剛好等於該品項的每件重量（八月 6 支品項逐一驗證無誤）
-- —— 也就是說，差別完全來自包裝規格，不是人的努力程度。
--
-- 八月實測：A1020（440g 玻璃瓶）與 B2011（2.8kg 馬口鐵）的單位/人·hr
-- 同樣是 280.1，但 kg/人·hr 差 6.4 倍（123 vs 784）。作業員的動作次數一樣多。
--
-- 用途因此要分清楚：
--   單位/人·hr → 跟自己比（趨勢、批次落差）。跨品項排名等於在罵做小包裝的人。
--   kg/人·hr   → 跨品項比（人力花在哪、哪種規格吃人力），給業務與生管看。

create view packing.labour_by_sku with (security_invoker = true) as
select
  b.sku_code,
  to_char(b.prod_date, 'YYYY-MM')                               as ym,
  count(*)                                                      as batches,
  count(b.headcount)                                            as with_head,
  round(100.0 * count(b.headcount) / count(*))                  as head_pct,
  sum(b.bottles)                                                as bottles,
  round(sum(b.hours), 2)                                        as hours,
  -- 以下只用「有填人數」的批次計算，混著算會讓數字失去意義
  sum(b.bottles)     filter (where b.headcount is not null)     as bottles_h,
  round(sum(b.hours) filter (where b.headcount is not null), 2) as hours_h,
  round(sum(b.bottles * s.unit_weight_kg * s.units_per_record)
        filter (where b.headcount is not null), 1)              as kg_h,
  round(sum(b.hours * b.headcount)
        filter (where b.headcount is not null), 2)              as person_hours,
  case when sum(b.hours * b.headcount) filter (where b.headcount is not null) > 0
       then round(sum(b.bottles) filter (where b.headcount is not null)
                  / sum(b.hours * b.headcount) filter (where b.headcount is not null), 1)
  end                                                           as per_person,
  case when sum(b.hours * b.headcount) filter (where b.headcount is not null) > 0
       then round(sum(b.bottles * s.unit_weight_kg * s.units_per_record)
                  filter (where b.headcount is not null)
                  / sum(b.hours * b.headcount) filter (where b.headcount is not null), 1)
  end                                                           as kg_per_person,
  max(s.unit_weight_kg * s.units_per_record)                    as pack_kg,
  round(avg(b.headcount), 1)                                    as avg_head,
  min(b.headcount)                                              as min_head,
  max(b.headcount)                                              as max_head
from packing.batches b
join packing.skus s on s.code = b.sku_code
group by b.sku_code, to_char(b.prod_date, 'YYYY-MM');

comment on view packing.labour_by_sku is
  '每個品項每月的人力投入。per_person（單位/人·hr）看作業強度、只跟自己比；'
  'kg_per_person（kg/人·hr）可跨品項比。兩者只用有填人數的批次計算，'
  'head_pct 是覆蓋率，低於 80% 的數字不應單獨引用。';


-- 同一支品項在不同配置人數下的表現。
-- 用途是問一個問題：加人之後，產出有沒有等比例增加？
--
-- 【重要】這張表看到的關聯不能當因果。現場通常是「預期這批難做才多派人」，
-- 所以「人多的批次比較慢」很可能是難做的批次本來就慢，不是人多造成的。
-- 這是提問的依據，不是結論。
create view packing.labour_by_headcount with (security_invoker = true) as
select
  b.sku_code,
  b.headcount,
  count(*)                                        as batches,
  sum(b.bottles)                                  as bottles,
  round(sum(b.hours), 2)                          as hours,
  round(sum(b.bottles) / sum(b.hours))            as line_rate,
  round(sum(b.bottles) / sum(b.hours * b.headcount), 1) as per_person
from packing.batches b
where b.headcount is not null
group by b.sku_code, b.headcount;

comment on view packing.labour_by_headcount is
  '同品項在不同人數配置下的產能。關聯不等於因果 —— 難做的批次往往本來就會多派人。';

grant select on packing.labour_by_sku, packing.labour_by_headcount
  to authenticated, service_role;
