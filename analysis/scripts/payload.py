#!/usr/bin/env python3
"""彙總 rows.json → payload.json（儀表板直接內嵌的資料）。

核心指標定義
  產能            = 瓶數 ÷ 工時
  每千瓶工時      = 1000 ÷ 產能        ← 儀表板主指標，現場語言、可直接乘接單量
  相對工時強度指數 = 工時佔比 ÷ 產量佔比 = 全廠平均產能 ÷ 該品項產能
                    只表示「比全廠平均慢幾倍」，須與工時佔比兩維度並用
  P75 目標        = 該品項各批次產能的第 75 百分位（自己跟自己比）
  可省工時        = 目前工時 − 若全數達 P75 所需工時
  效率指數        = 以各品項全年平均回推的應有工時 ÷ 實際工時 × 100
                    扣掉產品組合變動的影響，100 = 與全年平均同水準

用法： python3 payload.py [rows.json路徑] [輸出路徑]
"""
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

SHORT_BATCH_H = 1.0        # 零星批次門檻
INTENSITY_HIGH = 1.5       # 相對工時強度指數警戒
HOUR_SHARE_HIGH = 3.0      # 工時佔比警戒（%）
FRAGMENT_SHARE = 40.0      # 零星批次佔比警戒（%）
CV_HIGH = 25.0             # 批次變異警戒（%）
MIN_BATCHES = 10           # 變異規則的最小樣本數
MIN_HOURS = 20.0           # 變異規則的最小工時


def percentile75(values):
    """第 75 百分位，線性內插。

    與 rules.js 用同一種定義 —— statistics.quantiles 預設是 exclusive 法，
    算出來會偏高，兩邊的 P75 目標與可省工時就對不起來。
    """
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * 0.75
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (pos - lo)


def build(rows):
    total_b = sum(r["b"] for r in rows)
    total_h = sum(r["h"] for r in rows)
    overall_rate = total_b / total_h

    by_sku = defaultdict(list)
    for r in rows:
        by_sku[r["sku"]].append(r)

    skus = []
    for sku, batches in by_sku.items():
        rates = [b["b"] / b["h"] for b in batches]
        B = sum(b["b"] for b in batches)
        H = sum(b["h"] for b in batches)
        rate = B / H
        p75 = percentile75(rates)
        short = [b for b in batches if b["h"] < SHORT_BATCH_H]
        days = {b["date"] for b in batches}
        h_share = 100 * H / total_h
        intensity = overall_rate / rate
        # 品項層級：每月產能、是否連續 3 個月低於自己的中位數
        by_month = defaultdict(lambda: [0.0, 0.0])
        for r in batches:
            e = by_month[r["month"]]
            e[0] += r["b"]
            e[1] += r["h"]
        month_rates = [{"m": m, "rate": round(b / h)}
                       for m, (b, h) in sorted(by_month.items())]
        med = st.median(rates)
        last3 = month_rates[-3:]
        declining = len(month_rates) >= 3 and all(x["rate"] < med * 0.9 for x in last3)
        recent = {m["m"] for m in month_rates[-3:]}
        recent_rates = [r["b"] / r["h"] for r in batches if r["month"] in recent]
        vs_usual = (st.mean(recent_rates) / med - 1) if recent_rates else None

        skus.append({
            "sku": sku,
            "declining": declining, "vsUsual": vs_usual, "months": month_rates,
            "b": round(B),
            "h": round(H, 1),
            "d": len(days),
            "n": len(batches),
            "rate": round(rate),
            "hPer1k": round(1000 / rate, 2),
            "med": round(st.median(rates)),
            "p75": round(p75),
            "best": round(max(rates)),
            "worst": round(min(rates)),
            "cv": round(100 * st.pstdev(rates) / st.mean(rates)),
            "save": round(max(H - B / p75, 0), 1),
            "intensity": round(intensity, 2),
            "hShare": round(h_share, 2),
            "bShare": round(100 * B / total_b, 2),
            "shortN": len(short),
            "shortH": round(sum(b["h"] for b in short), 1),
            "shortShare": round(100 * len(short) / len(batches)),
            "perDay": round(len(batches) / len(days), 2),
            "avgBatchH": round(H / len(batches), 2),
        })
    skus.sort(key=lambda s: -s["b"])

    # 分析名單 = 量前 10 ∪ 天數前 10
    top_b = [s["sku"] for s in skus[:10]]
    top_d = [s["sku"] for s in sorted(skus, key=lambda s: -s["d"])[:10]]
    focus = sorted(set(top_b) | set(top_d))

    # 月趨勢 + 效率指數（以各品項全年平均回推應有工時）
    std_rate = {s["sku"]: s["rate"] for s in skus}
    buckets = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        m = buckets[r["month"]]
        m[0] += r["b"]
        m[1] += r["h"]
        m[2] += r["b"] / std_rate[r["sku"]]
    months = [{
        "m": m,
        "b": round(b),
        "h": round(h, 1),
        "rate": round(b / h),
        "expected": round(b / eh),
        "index": round(100 * eh / h),
    } for m, (b, h, eh) in sorted(buckets.items())]

    # 每日負載
    day_h = defaultdict(float)
    day_skus = defaultdict(set)
    for r in rows:
        day_h[r["date"]] += r["h"]
        day_skus[r["date"]].add(r["sku"])
    daily = sorted(day_h.values())
    over8 = [d for d, h in day_h.items() if h > 8]
    solo8 = []
    day_sku_h = defaultdict(float)
    for r in rows:
        day_sku_h[(r["date"], r["sku"])] += r["h"]
    for (date, sku), h in day_sku_h.items():
        if h > 8:
            solo8.append({"date": date, "sku": sku, "h": round(h, 2)})
    solo8.sort(key=lambda x: -x["h"])

    short_rows = [r for r in rows if r["h"] < SHORT_BATCH_H]
    pareto_n = 0
    cum = 0
    for s in skus:
        cum += s["b"]
        pareto_n += 1
        if cum >= 0.8 * total_b:
            break

    meta = {
        "period": [min(r["date"] for r in rows), max(r["date"] for r in rows)],
        "records": len(rows),
        "skuCount": len(skus),
        "workDays": len(day_h),
        "bottles": round(total_b),
        "hours": round(total_h, 1),
        "rate": round(overall_rate),
        "hPer1k": round(1000 / overall_rate, 2),
        "saveFocus": round(sum(s["save"] for s in skus if s["sku"] in focus), 1),
        "saveAll": round(sum(s["save"] for s in skus)),
        "focusBShare": round(sum(s["bShare"] for s in skus if s["sku"] in focus), 1),
        "focusHShare": round(sum(s["hShare"] for s in skus if s["sku"] in focus), 1),
        "paretoN": pareto_n,
        "shortN": len(short_rows),
        "shortH": round(sum(r["h"] for r in short_rows)),
        "shortShare": round(100 * len(short_rows) / len(rows)),
        "dayMedian": round(st.median(daily), 1),
        "dayMax": round(max(daily), 1),
        "over8Days": len(over8),
        "solo8": solo8,
    }
    return {"meta": meta, "skus": skus, "focus": focus, "months": months,
            "alerts": alerts(skus, months, meta, focus),
            "batches": [{"s": r["sku"], "d": r["date"], "h": r["h"], "b": round(r["b"])}
                        for r in rows]}


def alerts(skus, months, meta, focus):
    """兩條全廠層級的規則，與 rules.js 一致。

    其餘提醒（批次落差、零星批次、集中度）改在儀表板點進單一品項時才出現；
    「批次過碎」整條移除 —— 接單式生產，批量由訂單與排程決定，不是包裝可控。
    """
    out = []

    heavy = sorted(
        (s for s in skus
         if s["intensity"] > INTENSITY_HIGH and s["hShare"] >= HOUR_SHARE_HIGH),
        key=lambda s: -s["hShare"])
    if heavy:
        out.append({
            "id": "heavy", "level": "info", "owner": "業務 / 生管",
            "title": "吃工時但產量不高的品項",
            "rule": f"每千瓶工時高於全廠平均 {INTENSITY_HIGH} 倍，"
                    f"且占全廠工時 {HOUR_SHARE_HIGH}% 以上",
            "why": "這不是包裝作業的問題 —— 瓶型與接單方式決定了它就是慢。"
                   "提供給業務與生管參考：接單與排程時，這類品項的工時成本要先估進去。"
                   f"（全廠另有 {meta['shortN']} 批未滿 1 小時，合計 {meta['shortH']} 小時"
                   f"＝總工時的 {round(100 * meta['shortH'] / meta['hours'])}%。）",
            "items": [{"sku": s["sku"],
                       "value": f"每千瓶 {s['hPer1k']} 小時，是全廠平均的 {s['intensity']} 倍",
                       "detail": f"只做了全廠 {s['bShare']}% 的瓶數，"
                                 f"卻用掉 {s['hShare']}% 的工時"}
                      for s in heavy],
        })

    declining = [s for s in skus if s.get("declining")]
    declining.sort(key=lambda s: s["vsUsual"])
    if declining:
        out.append({
            "id": "declining", "level": "high", "owner": "包裝單位",
            "title": "連續 3 個月比自己平常慢的品項",
            "rule": "最近 3 個有生產的月份，月產能全部低於該品項自己的中位數 10% 以上",
            "why": "跟自己比，不受瓶型差異影響，所以這是真的變慢了。",
            "items": [{"sku": s["sku"],
                       "value": f"近期比平常慢 {round(-100 * s['vsUsual'])}%",
                       "detail": "平常 {:,} → 最近 {} 瓶/工時".format(
                           s["med"], " / ".join(f"{m['rate']:,}" for m in s["months"][-3:]))}
                      for s in declining],
        })
    return out


def main():
    base = Path(__file__).resolve().parent.parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "rows.json"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "payload.json"
    rows = json.loads(src.read_text(encoding="utf-8"))["rows"]
    payload = build(rows)
    dst.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    m = payload["meta"]
    print(f"品項 {m['skuCount']}　紀錄 {m['records']:,}　作業日 {m['workDays']}")
    print(f"總量 {m['bottles']:,} 瓶　總工時 {m['hours']:,} h　"
          f"平均產能 {m['rate']:,} 瓶/工時（{m['hPer1k']} h/千瓶）")
    print(f"重點 {len(payload['focus'])} 支可省 {m['saveFocus']} h　"
          f"全品項可省 {m['saveAll']} h（{round(100 * m['saveAll'] / m['hours'])}%）")
    print(f"警示 {len(payload['alerts'])} 條："
          + "、".join(f"{a['title']}({len(a['items'])})" for a in payload["alerts"]))
    print(f"輸出 {dst}（{dst.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
