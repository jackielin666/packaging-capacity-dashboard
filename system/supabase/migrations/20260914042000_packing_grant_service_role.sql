-- service_role 是後台／伺服器端專用金鑰，不會出現在瀏覽器，給它完整權限以便日後維運。
-- 刻意「不」授權給 anon —— 未登入的人不應該讀到任何包裝資料。
grant usage on schema packing to service_role;
grant all on all tables in schema packing to service_role;
grant all on all routines in schema packing to service_role;
grant all on all sequences in schema packing to service_role;

alter default privileges for role postgres in schema packing grant all on tables to service_role;
alter default privileges for role postgres in schema packing grant all on routines to service_role;
alter default privileges for role postgres in schema packing grant all on sequences to service_role;
