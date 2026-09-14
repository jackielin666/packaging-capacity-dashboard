-- 包裝產能系統：獨立 schema，與既有的巡檢系統（public）完全隔離
create schema if not exists packing;

-- ── 使用者角色 ──────────────────────────────────────────────
create table packing.members (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  role       text not null check (role in ('operator','manager','viewer')),
  created_at timestamptz not null default now()
);
comment on table packing.members is 'operator=輸入專員、manager=主管、viewer=檢視者';

create or replace function packing.my_role() returns text
language sql stable security definer set search_path = packing, public as $$
  select role from packing.members where user_id = auth.uid();
$$;

-- ── 品項主檔 ────────────────────────────────────────────────
create table packing.skus (
  code             text primary key,
  name             text not null,
  unit_weight_kg   numeric(8,3),
  units_per_record smallint not null default 1 check (units_per_record >= 1),
  container        text,
  active           boolean not null default true,
  note             text,
  updated_at       timestamptz not null default now()
);
comment on column packing.skus.unit_weight_kg   is '單一包裝件的淨重（公斤）';
comment on column packing.skus.units_per_record is '一筆記錄的「瓶數」代表幾個包裝件。一般為 1；D0420/D0422 一箱 3 包故為 3';
comment on column packing.skus.container        is 'PE袋／玻璃瓶／白桶／馬口鐵／PET瓶／鐵桶／袋裝';

-- ── 批次記錄（主表）──────────────────────────────────────────
create table packing.batches (
  id          bigint generated always as identity primary key,
  sku_code    text not null references packing.skus(code) on update cascade,
  prod_date   date not null,
  start_time  time not null,
  end_time    time not null,
  -- 工時一律由起訖時間推算，不接受人工輸入（跨午夜自動加 24 小時）
  hours       numeric(6,3) generated always as (
                round((extract(epoch from (end_time - start_time))
                       + case when end_time < start_time then 86400 else 0 end) / 3600.0, 3)
              ) stored,
  bottles     integer not null check (bottles > 0),
  headcount   smallint check (headcount between 1 and 99),
  note        text,
  source      text not null default 'manual' check (source in ('manual','import')),
  created_by  uuid references auth.users(id),
  created_at  timestamptz not null default now(),
  updated_by  uuid references auth.users(id),
  updated_at  timestamptz not null default now(),
  constraint batches_hours_positive check (start_time <> end_time)
);
comment on column packing.batches.bottles is '記錄單位的數量。實際包裝件數 = bottles × skus.units_per_record';

create index batches_date_idx on packing.batches (prod_date desc);
create index batches_sku_date_idx on packing.batches (sku_code, prod_date desc);

-- ── 每日狀態：區分「當天沒生產」與「忘了登記」──────────────────
create table packing.daily_status (
  prod_date    date primary key,
  no_operation boolean not null default true,
  note         text,
  marked_by    uuid references auth.users(id),
  marked_at    timestamptz not null default now()
);
comment on table packing.daily_status is '標記當日確實無包裝作業（含國定假日、停工）。未標記又無批次記錄者即為漏登';

-- ── 稽核記錄 ────────────────────────────────────────────────
create table packing.audit_log (
  id         bigint generated always as identity primary key,
  table_name text not null,
  row_key    text not null,
  action     text not null check (action in ('INSERT','UPDATE','DELETE')),
  before_val jsonb,
  after_val  jsonb,
  changed_by uuid references auth.users(id),
  changed_at timestamptz not null default now()
);
create index audit_log_changed_at_idx on packing.audit_log (changed_at desc);

create or replace function packing.write_audit() returns trigger
language plpgsql security definer set search_path = packing, public as $$
begin
  insert into packing.audit_log(table_name, row_key, action, before_val, after_val, changed_by)
  values (tg_table_name,
          coalesce((to_jsonb(new)->>'id'), (to_jsonb(old)->>'id'),
                   (to_jsonb(new)->>'code'), (to_jsonb(old)->>'code'),
                   (to_jsonb(new)->>'prod_date'), (to_jsonb(old)->>'prod_date')),
          tg_op,
          case when tg_op in ('UPDATE','DELETE') then to_jsonb(old) end,
          case when tg_op in ('INSERT','UPDATE') then to_jsonb(new) end,
          auth.uid());
  return coalesce(new, old);
end $$;

create trigger batches_audit after insert or update or delete on packing.batches
  for each row execute function packing.write_audit();
create trigger skus_audit after insert or update or delete on packing.skus
  for each row execute function packing.write_audit();

-- 自動維護 updated_at / updated_by
create or replace function packing.touch_row() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  if tg_table_name = 'batches' then new.updated_by := auth.uid(); end if;
  return new;
end $$;
create trigger batches_touch before update on packing.batches
  for each row execute function packing.touch_row();
create trigger skus_touch before update on packing.skus
  for each row execute function packing.touch_row();
