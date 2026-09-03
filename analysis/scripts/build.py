#!/usr/bin/env python3
"""把 payload.json 灌回 index.html —— 每月更新只要跑這一支。

index.html 內的資料夾在 /*PAYLOAD:START*/ … /*PAYLOAD:END*/ 之間，
這支腳本只替換那一段，版面與程式碼完全不動，可以重複執行。

用法： python3 build.py [payload.json路徑] [index.html路徑]
"""
import re
import sys
from pathlib import Path

MARKER = re.compile(r"/\*PAYLOAD:START\*/.*?/\*PAYLOAD:END\*/", re.S)


def main():
    base = Path(__file__).resolve().parent.parent
    payload = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "payload.json"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else base.parent / "index.html"

    data = payload.read_text(encoding="utf-8").strip()
    html = target.read_text(encoding="utf-8")
    if not MARKER.search(html):
        sys.exit(f"找不到 PAYLOAD 標記，請確認 {target} 沒有被改壞")
    out = MARKER.sub(lambda _: f"/*PAYLOAD:START*/{data}/*PAYLOAD:END*/", html, count=1)
    target.write_text(out, encoding="utf-8")
    print(f"已更新 {target}（資料 {len(data) / 1024:.0f} KB，總計 {len(out) / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
