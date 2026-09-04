#!/usr/bin/env python3
"""端到端测截图路径：群聊截图 → 多模态 OCR 抽主张 → agent 核查。"""
import base64
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.run import run_check

IMG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "static", "sample_chat.png")

with open(IMG, "rb") as f:
    uri = "data:image/png;base64," + base64.b64encode(f.read()).decode()

events = []
t0 = time.time()
report = run_check("image", uri, events)
elapsed = time.time() - t0

print(f"\n===== 截图核查完成（{elapsed:.0f}s）=====")
src = report.get("source", {})
print(f"OCR 识别字数: {len(src.get('ocr_text',''))}")
print(f"OCR 片段: {src.get('ocr_text','')[:120]}")
ov = report.get("overall", {})
print(f"\n总结论: {ov.get('headline')} — {ov.get('lead')}")
for c in report.get("claims", []):
    srcs = c.get("sources", [])
    auth = [s for s in srcs if s.get("is_authoritative")]
    print(f"\n[{c.get('rating')}|{c.get('confidence')}] {c.get('claim','')[:40]}")
    print(f"  大白话: {c.get('plain','')[:70]}")
    print(f"  信源 {len(srcs)} 张(权威{len(auth)}): " + "; ".join(s.get("site","") for s in srcs))
ec = report.get("elder_card", {})
print(f"\n长辈卡片: {ec.get('headline')} | {ec.get('said','')[:40]}")
for fct in ec.get("facts", []):
    print(f"  · {fct}")
