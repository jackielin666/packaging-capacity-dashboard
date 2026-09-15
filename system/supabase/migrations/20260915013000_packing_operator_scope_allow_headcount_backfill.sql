-- 原本的規則是「輸入專員只能改當月」，實測發現擋掉了兩件該做的事：
--
--   1. 補登舊月份的人數。這是階段 4 人均效率分析唯一的依據，Jackie 哥明確
--      要求專人回頭補，時間會拉很長，不可能都落在當月。
--   2. 月初才收到上個月最後幾天的資料，登記完發現打錯要改 —— 那一筆的
--      生產日期已經是上個月，改不動。
--
-- 新規則分成兩層，量的部分保護、質的部分開放：
--
--   ‧ 生產日期在「上個月 1 號」之後  → 整筆都可以改
--   ‧ 更早的資料                    → 只能補人數、備註、確認異常，
--                                      品項／日期／時間／瓶數一律不可動
--
-- 這樣補登補得下去，但歷史的「量測值」不會被無聲改掉。

create or replace function packing.editable_from_tw() returns date
language sql stable
set search_path = pg_catalog, public
as $$ select (date_trunc('month', packing.today_tw()) - interval '1 month')::date $$;

comment on function packing.editable_from_tw is
  '輸入專員可以整筆修改的最早生產日期＝上個月 1 號。更早的只能補人數與備註。';

-- 放寬 UPDATE 的列範圍，改由底下的觸發器決定「哪些欄位」可以動。
-- RLS 只能管到「哪幾列」，管不到「哪幾欄」，所以欄位層級要用觸發器。
drop policy if exists batches_update_operator on packing.batches;
create policy batches_update_operator on packing.batches for update
  to authenticated
  using      (packing.my_role() = 'operator')
  with check (packing.my_role() = 'operator');

-- 刪除仍然只放寬到上個月。刪掉一整批不是「補登」，是抹除紀錄。
drop policy if exists batches_delete_operator on packing.batches;
create policy batches_delete_operator on packing.batches for delete
  to authenticated
  using (packing.my_role() = 'operator' and prod_date >= packing.editable_from_tw());

create or replace function packing.guard_operator_scope() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  if packing.my_role() is distinct from 'operator' then return new; end if;
  if new.prod_date >= packing.editable_from_tw()
     and old.prod_date >= packing.editable_from_tw() then return new; end if;

  -- 舊資料：只開放補人數、備註與異常確認
  if new.sku_code   is distinct from old.sku_code
  or new.prod_date  is distinct from old.prod_date
  or new.start_time is distinct from old.start_time
  or new.end_time   is distinct from old.end_time
  or new.bottles    is distinct from old.bottles then
    raise exception '% 以前的資料只能補人數與備註，品項、日期、時間、瓶數要請主管修改。',
      to_char(packing.editable_from_tw(), 'YYYY-MM-DD')
      using errcode = 'check_violation';
  end if;

  return new;
end $$;

drop trigger if exists batches_operator_scope on packing.batches;
create trigger batches_operator_scope
  before update on packing.batches
  for each row execute function packing.guard_operator_scope();
