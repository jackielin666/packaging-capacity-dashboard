-- 1) 固定 search_path，避免 SECURITY DEFINER 函式被 search_path 劫持
alter function packing.today_tw()       set search_path = pg_catalog, public;
alter function packing.month_start_tw() set search_path = pg_catalog, public;
alter function packing.touch_row()      set search_path = pg_catalog, public;

-- 2) 一次性匯入用的 helper 已完成任務，移除以縮小攻擊面
drop function if exists packing.import_blob(text);
