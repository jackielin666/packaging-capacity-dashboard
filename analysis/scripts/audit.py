#!/usr/bin/env python3
"""資料檢核：每月更新前先跑這支，確認來源資料乾淨才往下做。

檢核七項：
  1. 解析階段擋掉的異常（日期無法解析／工時空白、為零或負數／瓶數空白）
  2. 工時 != 結束-起始（手動覆寫過）
  3. 混包寫法（A200/B209）
  4. 空白工作表（建檔但整年沒生產）
  5. 欄位標題不符
  6. 極短批次（<0.5h）—— 會把該品項的「歷史最佳」灌水，僅提示不排除
  7. 產能明顯偏離的批次 —— 超過該品項中位數 2.5 倍或低於 0.4 倍。
     目的是抓資料登打錯誤，與儀表板上「離群批次」（平均 ×0.7）用途不同

用法： python3 audit.py [rows.json路徑]
"""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

SHORT_BATCH_H = 0.5
OUTLIER_HIGH, OUTLIER_LOW = 2.5, 0.4


def to_minutes(t):
    if not t:
        return None
    try:
        h, m = str(t).split(":")[:2]
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def audit(rows, meta):
    findings = defaultdict(list)

    for issue in meta["issues"]:
        findings[issue["kind"]].append(issue)
    for sheet in meta["header_mismatch"]:
        findings["欄位標題不符"].append(sheet)

    for r in rows:
        a, b = to_minutes(r["start"]), to_minutes(r["end"])
        if a is not None and b is not None and abs((b - a) / 60 - r["h"]) > 0.02:
            findings["工時與起訖時間不符"].append(
                {**r, "計算值": round((b - a) / 60, 2)})
        if r["mixed"]:
            findings["混包寫法（已加總）"].append(r)
        if r["h"] < SHORT_BATCH_H:
            findings[f"極短批次（<{SHORT_BATCH_H}h）"].append(r)

    by_sku = defaultdict(list)
    for r in rows:
        by_sku[r["sku"]].append(r)
    for sku, batches in by_sku.items():
        if len(batches) < 5:
            continue
        med = st.median(b["b"] / b["h"] for b in batches)
        for b in batches:
            rate = b["b"] / b["h"]
            if rate > med * OUTLIER_HIGH or rate < med * OUTLIER_LOW:
                findings["產能明顯偏離（疑似登打錯誤）"].append(
                    {**b, "產能": round(rate), "該品項中位": round(med)})

    return findings, meta["empty_sheets"]


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent.parent / "rows.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows, meta = data["rows"], data["meta"]
    findings, empty = audit(rows, meta)

    blocking = ["日期無法解析", "工時空白", "工時為零或負數", "瓶數空白",
                "欄位標題不符", "工時與起訖時間不符"]
    print(f"檢核 {len(rows):,} 筆紀錄\n")

    print("【必須修正】")
    hard = {k: v for k, v in findings.items() if k in blocking}
    if not hard:
        print("  無 —— 資料乾淨，可以往下做\n")
    for kind, items in hard.items():
        print(f"  {kind}：{len(items)} 筆")
        for it in items[:10]:
            print(f"    {it.get('sku')} {it.get('date')} {it}")
        print()

    print("【僅供判讀，不影響計算】")
    for kind, items in findings.items():
        if kind in blocking:
            continue
        print(f"  {kind}：{len(items)} 筆")
        for it in items[:5]:
            extra = f" 產能 {it['產能']:,} vs 中位 {it['該品項中位']:,}" if "產能" in it else ""
            print(f"    {it['sku']} {it['date']} {it['h']:.2f}h {it['b']:,.0f}瓶{extra}")
        if len(items) > 5:
            print(f"    …另外 {len(items) - 5} 筆")
    print(f"\n  空白工作表：{len(empty)} 個 —— {', '.join(empty)}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
