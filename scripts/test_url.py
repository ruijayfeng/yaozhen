#!/usr/bin/env python3
"""端到端测链接路径：公众号/网页 URL → fetch 抓正文 → 抽主张 → agent 核查。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.run import run_check

URL = sys.argv[1] if len(sys.argv) > 1 else \
    "http://www.xinhuanet.com/politics/2016-11/18/c_129368956.htm"

events = []
t0 = time.time()
try:
    report = run_check("url", URL, events)
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"\n💥 链接路径失败: {type(e).__name__}: {e}")
    sys.exit(1)
elapsed = time.time() - t0

src = report.get("source", {})
print(f"\n===== 链接核查完成（{elapsed:.0f}s）=====")
print(f"标题: {src.get('title','')[:50]}")
print(f"抓取正文字数: {src.get('chars')}")
ov = report.get("overall", {})
print(f"\n总结论: {ov.get('headline')} — {ov.get('lead')}")
for c in report.get("claims", []):
    srcs = c.get("sources", [])
    auth = [s for s in srcs if s.get("is_authoritative")]
    print(f"\n[{c.get('rating')}|{c.get('confidence')}] {c.get('claim','')[:42]}")
    print(f"  大白话: {c.get('plain','')[:66]}")
    print(f"  信源 {len(srcs)} 张(权威{len(auth)}): " + "; ".join(s.get("site","") for s in srcs))
ec = report.get("elder_card", {})
if ec:
    print(f"\n长辈卡片: {ec.get('headline')} | {ec.get('said','')[:36]}")
    for fct in ec.get("facts", [])[:4]:
        print(f"  · {fct}")
