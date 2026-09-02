# 包裝產能分析（規劃階段）

資料來源：`包裝工時記錄表_2026.08.28.xlsx`（122 個工作表，109 個有資料）

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `plan.html` | 分析與執行規劃報告（可直接開啟） |
| `data-summary.json` | 全表彙總結果（Top10、重點品項落差、月趨勢） |
| `scripts/extract.py` | 讀取 xlsx，逐列解析並做品質稽核 → `rows.json` |
| `scripts/payload.py` | 依 rows.json 產生彙總 → `payload.json` |

## 重跑方式

```bash
pip install openpyxl
python3 scripts/extract.py     # 需先在檔內指定 xlsx 路徑
python3 scripts/payload.py
```

## 重要前提

- 原始資料的「包裝日期」欄沒有年份。109 個工作表全部依 10月→8月 排序且零違反，
  因此推定資料期間為 **2025-10-01 ~ 2026-08-26**。若實際橫跨更多年份，需重算。
- 「工時」＝結束時間 − 起始時間（掛鐘時間），**不是人工時**（無作業人數欄位）。
