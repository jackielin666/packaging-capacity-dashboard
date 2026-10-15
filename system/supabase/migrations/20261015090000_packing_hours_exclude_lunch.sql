-- 工時扣除午休 12:00–13:00。
--
-- 廠助反映：A1032 10/13 08:50–13:15 算成 4.42 小時，中午休息的 1 小時沒扣。
-- 查證後，原本的工時就是「結束 − 起始」，歷史 Excel 也是 (結束 − 起始) × 24，
-- 從來沒有扣休息。全部 1,792 批中有 232 批整段跨過午休，共多算 232 小時
-- （總工時的 7.3%），這些批次的產能中位數被低估 32%，儀表板上有一部分
-- 「慢的批次」其實是午休造成的。
--
-- Jackie 哥確認：午休整條線都會停，自動扣除，歷史資料一起重算；17:00 之後不扣。
--
-- 做法：只改 hours 這個生成欄位的算式，起訖時間的原始紀錄不動。
--   工時 ＝ 結束 − 起始（跨午夜加 24 小時）− 與 12:00–13:00 重疊的時間
--   跨午夜的批次拆成 [起始, 24:00) 與 [00:00, 結束) 兩段各自扣重疊。
-- 套用前試算：232 批改變、共扣 232.00 小時、沒有批次變成 0。
-- 輸入頁 calcHours() 同步同一套算法。

alter table packing.batches alter column hours set expression as (
  round(((extract(epoch from end_time) - extract(epoch from start_time)
          + case when end_time < start_time then 86400 else 0 end)
         - case when end_time >= start_time
                then greatest(0, least(extract(epoch from end_time), 46800) - greatest(extract(epoch from start_time), 43200))
                else greatest(0, 46800 - greatest(extract(epoch from start_time), 43200))
                   + greatest(0, least(extract(epoch from end_time), 46800) - 43200) end
        )::numeric / 3600.0, 3)
);

-- 整批都落在午休裡（例如 12:10–12:40）扣完是 0 小時，產能會除以零。
-- 建表時就有的 batches_hours_positive（hours > 0）會直接擋下，不需另加。
