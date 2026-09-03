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
    return st.quantiles(values, n=4)[2] if len(values) > 3 else max(values)


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
        skus.append({
            "sku": sku,
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
    """六條偵測規則 —— 每月重跑就能自動列出踩線項目。"""
    out = []

    hogs = [s for s in skus
            if s["intensity"] > INTENSITY_HIGH and s["hShare"] >= HOUR_SHARE_HIGH]
    if hogs:
        out.append({
            "id": "intensity",
            "level": "high",
            "title": "資源佔用偏高的品項",
            "rule": f"相對工時強度指數 > {INTENSITY_HIGH} 且 工時佔比 ≥ {HOUR_SHARE_HIGH}%",
            "why": "產量佔比小、工時佔比大。先確認是瓶型使然還是排程造成，"
                   "再決定要合批還是調線。",
            "items": [{"sku": s["sku"],
                       "value": f"指數 {s['intensity']}　工時佔比 {s['hShare']}%",
                       "detail": f"{s['hPer1k']} h/千瓶　{s['n']} 批 / {s['d']} 天"}
                      for s in sorted(hogs, key=lambda s: -s["hShare"])],
        })

    frag = [s for s in skus if s["shortShare"] > FRAGMENT_SHARE and s["hShare"] >= 1.0]
    if frag:
        out.append({
            "id": "fragment",
            "level": "high",
            "title": "批次過碎，有合批機會",
            "rule": f"單批 < {SHORT_BATCH_H:g} 小時的批次佔比 > {FRAGMENT_SHARE}%（且工時佔比 ≥ 1%）",
            "why": "零星批次的準備與換線成本無法攤提。改善方向是合批，不是要求線上加快。",
            "items": [{"sku": s["sku"],
                       "value": f"{s['shortN']}/{s['n']} 批未滿 1 小時（{s['shortShare']}%）",
                       "detail": f"這些批次合計 {s['shortH']} h，佔該品項 "
                                 f"{round(100 * s['shortH'] / s['h'])}% 工時"}
                      for s in sorted(frag, key=lambda s: -s["shortH"])],
        })

    tail = months[-3:]
    if all(m["index"] < 100 for m in tail):
        out.append({
            "id": "trend",
            "level": "high",
            "title": "效率指數連續 3 個月低於基準",
            "rule": "扣除產品組合影響後的效率指數連續 3 個月 < 100",
            "why": "指數已排除「低速品項變多」的影響，因此這是真實的效率退步，"
                   "不是產品組合造成的錯覺。",
            "items": [{"sku": m["m"],
                       "value": f"指數 {m['index']}",
                       "detail": f"實際 {m['rate']:,} vs 組合預期 {m['expected']:,} 瓶/工時"}
                      for m in tail],
        })

    varied = [s for s in skus
              if s["cv"] > CV_HIGH and s["n"] >= MIN_BATCHES and s["h"] >= MIN_HOURS]
    if varied:
        out.append({
            "id": "variance",
            "level": "mid",
            "title": "同品項批次落差過大",
            "rule": f"批次產能變異係數 CV > {CV_HIGH}%（樣本 ≥ {MIN_BATCHES} 批、"
                    f"工時 ≥ {MIN_HOURS:g} h）",
            "why": "同一支產品、同一條線，批次之間差三成以上就是管理落差，"
                   "不是產品特性。這是最直接的改善標的。",
            "items": [{"sku": s["sku"],
                       "value": f"CV {s['cv']}%　可省 {s['save']} h",
                       "detail": f"中位 {s['med']:,} → P75 目標 {s['p75']:,} 瓶/工時"}
                      for s in sorted(varied, key=lambda s: -s["save"])[:12]],
        })

    out.append({
        "id": "fragment_total",
        "level": "mid",
        "title": "零星批次的整體成本",
        "rule": f"全廠單批 < {SHORT_BATCH_H:g} 小時的批次數與工時合計",
        "why": "這是「批次過碎」在全廠層級的總帳，可用來評估合批專案的效益上限。",
        "items": [{"sku": "全廠合計",
                   "value": f"{meta['shortN']} 批（{meta['shortShare']}%）",
                   "detail": f"合計 {meta['shortH']} h，佔總工時 "
                             f"{round(100 * meta['shortH'] / meta['hours'])}%"}],
    })

    out.append({
        "id": "pareto",
        "level": "info",
        "title": "產出集中度",
        "rule": "Pareto 累積曲線",
        "why": "分析與改善資源不需要平均分配到 109 支產品上。",
        "items": [{"sku": f"前 {meta['paretoN']} 支",
                   "value": f"佔 80% 包裝量",
                   "detail": f"共 {meta['skuCount']} 支品項；"
                             f"重點 {len(focus)} 支佔 {meta['focusBShare']}% 量、"
                             f"{meta['focusHShare']}% 工時"}],
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
