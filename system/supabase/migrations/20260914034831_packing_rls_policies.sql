-- 台灣時區的「今天」與「本月起日」，避免 UTC 造成月初月底判斷錯誤
create or replace function packing.today_tw() returns date
language sql stable as $$ select (now() at time zone 'Asia/Taipei')::date $$;

create or replace function packing.month_start_tw() returns date
language sql stable as $$ select date_trunc('month', packing.today_tw())::date $$;

alter table packing.members      enable row level security;
alter table packing.skus         enable row level security;
alter table packing.batches      enable row level security;
alter table packing.daily_status enable row level security;
alter table packing.audit_log    enable row level security;

-- 讀取：三種角色都能看全部資料
create policy members_read on packing.members for select
  to authenticated using (packing.my_role() is not null);
create policy skus_read on packing.skus for select
  to authenticated using (packing.my_role() is not null);
create policy batches_read on packing.batches for select
  to authenticated using (packing.my_role() is not null);
create policy daily_read on packing.daily_status for select
  to authenticated using (packing.my_role() is not null);
create policy audit_read on packing.audit_log for select
  to authenticated using (packing.my_role() = 'manager');

-- 批次：輸入專員可新增，並只能改「本月」；主管不受月份限制
create policy batches_insert on packing.batches for insert
  to authenticated with check (packing.my_role() in ('operator','manager'));

create policy batches_update_operator on packing.batches for update
  to authenticated
  using  (packing.my_role() = 'operator' and prod_date >= packing.month_start_tw())
  with check (packing.my_role() = 'operator' and prod_date >= packing.month_start_tw());

create policy batches_update_manager on packing.batches for update
  to authenticated using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');

create policy batches_delete_operator on packing.batches for delete
  to authenticated using (packing.my_role() = 'operator' and prod_date >= packing.month_start_tw());
create policy batches_delete_manager on packing.batches for delete
  to authenticated using (packing.my_role() = 'manager');

-- 每日狀態：同樣的月份限制
create policy daily_write_operator on packing.daily_status for all
  to authenticated
  using  (packing.my_role() = 'operator' and prod_date >= packing.month_start_tw())
  with check (packing.my_role() = 'operator' and prod_date >= packing.month_start_tw());
create policy daily_write_manager on packing.daily_status for all
  to authenticated using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');

-- 品項主檔：只有主管能改（含日後補容器型式）
create policy skus_write_manager on packing.skus for all
  to authenticated using (packing.my_role() = 'manager') with check (packing.my_role() = 'manager');

-- 稽核記錄不可被任何人修改或刪除（只有觸發器以 security definer 寫入）
revoke insert, update, delete on packing.audit_log from authenticated, anon;

grant usage on schema packing to authenticated;
grant select on all tables in schema packing to authenticated;
grant insert, update, delete on packing.batches, packing.daily_status, packing.skus to authenticated;
grant usage, select on all sequences in schema packing to authenticated;
