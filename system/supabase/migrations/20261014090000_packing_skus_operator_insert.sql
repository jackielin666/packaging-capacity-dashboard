-- 讓輸入專員（廠助）可以自行新增品項。
--
-- 品項主檔之後會被其他系統拿來參照（製成率、效率分析都用 code 對應），
-- 所以開放新增的同時要守住三件事：
--   1. 只能「新增」：專員不能改名、刪除或停用既有品項，那仍是主管的權限。
--      改錯一個品名，所有引用它的報表都會跟著錯。
--   2. 格式一致：品號一律大寫、去空白，符合既有的編碼規則（字母開頭、
--      4～10 碼英數字，可帶「-1」這類尾碼），避免 d2233 與 D2233 變成兩支品項。
--   3. 查得到是誰建的：created_by／created_at，加上既有的 skus_audit 稽核紀錄。

alter table packing.skus add column if not exists created_by uuid;
alter table packing.skus add column if not exists created_at timestamptz;
alter table packing.skus alter column created_by set default auth.uid();
alter table packing.skus alter column created_at set default now();

alter table packing.skus add constraint skus_code_format
  check (code ~ '^[A-Z][0-9A-Z]{3,9}(-[0-9A-Z]{1,4})?$');
alter table packing.skus add constraint skus_name_present
  check (btrim(name) <> '');
alter table packing.skus add constraint skus_unit_weight_range
  check (unit_weight_kg is null or (unit_weight_kg > 0 and unit_weight_kg <= 100));

-- 送進來的值先整理：品號轉大寫去空白、品名與容器去頭尾空白。
-- 專員新增的品項一律啟用，建立者與時間由資料庫蓋章，不採用前端送來的值。
create or replace function packing.skus_normalize() returns trigger
language plpgsql
set search_path = pg_catalog, public
as $$
begin
  new.code := upper(btrim(new.code));
  new.name := btrim(new.name);
  new.container := nullif(btrim(coalesce(new.container, '')), '');
  if tg_op = 'INSERT' then
    new.created_by := auth.uid();
    new.created_at := now();
    if packing.my_role() = 'operator' then
      new.active := true;
      new.units_per_record := 1;
    end if;
  end if;
  return new;
end $$;

create trigger skus_normalize
  before insert or update on packing.skus
  for each row execute function packing.skus_normalize();

-- 專員只開放 INSERT；UPDATE／DELETE 仍只有 skus_write_manager（主管）。
create policy skus_insert_operator on packing.skus for insert
  to authenticated
  with check (packing.my_role() = 'operator');
