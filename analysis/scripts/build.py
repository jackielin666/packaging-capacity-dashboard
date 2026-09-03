#!/usr/bin/env python3
"""把 rows.json 的逐批次紀錄灌回 index.html —— 每月更新的最後一步。

儀表板的所有計算都在瀏覽器端由 rules.js 完成（使用者上傳檔案時走的是同一條路），
所以這裡只需要把「原始批次紀錄」放進去，不需要預先算好指標。
這樣內建資料與上傳資料不可能算出不一樣的結果。

替換範圍僅限 index.html 裡 /*PAYLOAD:START*/ … /*PAYLOAD:END*/ 之間那一段，
版面與程式碼不會被動到，可以重複執行。

用法： python3 build.py [rows.json路徑] [index.html路徑]
"""
import json
import re
import sys
from pathlib import Path

MARKER = re.compile(r"/\*PAYLOAD:START\*/.*?/\*PAYLOAD:END\*/", re.S)


def main():
    base = Path(__file__).resolve().parent.parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "rows.json"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else base.parent / "index.html"

    rows = json.loads(src.read_text(encoding="utf-8"))["rows"]
    if not rows:
        sys.exit("rows.json 沒有資料，請先跑 extract.py")

    batches = [{"s": r["sku"], "d": r["date"], "m": r["month"], "h": r["h"], "b": r["b"]}
               | ({"mixed": True} if r.get("mixed") else {})
               for r in rows]
    # 起始年度：資料以 10月→隔年9月 為一週期，10-12 月所屬的那一年即為起始年
    start_year = min(int(r["date"][:4]) for r in rows if int(r["month"][5:7]) >= 10) \
        if any(int(r["month"][5:7]) >= 10 for r in rows) \
        else min(int(r["date"][:4]) for r in rows)

    payload = json.dumps({"year": start_year, "batches": batches},
                         ensure_ascii=False, separators=(",", ":"))

    html = target.read_text(encoding="utf-8")
    if not MARKER.search(html):
        sys.exit(f"找不到 PAYLOAD 標記，請確認 {target} 沒有被改壞")
    out = MARKER.sub(lambda _: f"/*PAYLOAD:START*/{payload}/*PAYLOAD:END*/", html, count=1)
    target.write_text(out, encoding="utf-8")

    print(f"已更新 {target}")
    print(f"  批次紀錄 {len(batches):,} 筆　起始年度 {start_year}")
    print(f"  資料 {len(payload) / 1024:.0f} KB　整頁 {len(out) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
