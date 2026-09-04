#!/usr/bin/env python3
"""agent 循环冒烟测试：一条主张，打印事件流和最终判决。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.agent import verify_claim_agentic

claim = sys.argv[1] if len(sys.argv) > 1 else "味精加热超过100度会产生致癌物"
events = []
def emit(ev):
    events.append(ev)
    tag = f" [{ev.get('tag_text')}]" if ev.get("tag_text") else ""
    print(f"  {ev.get('icon','')} {ev.get('title','')}{tag}")
    if ev.get("detail"): print(f"      └ {ev['detail']}")

print(f"待核查：{claim}\n" + "="*60)
v = verify_claim_agentic(claim, emit)
print("="*60)
print(json.dumps({k: v[k] for k in ("rating","confidence","plain","evidence","conflict","authority_hit","stats")},
                 ensure_ascii=False, indent=2))
print("证据卡：")
for s in v["sources"]:
    print(f"  [{s['level']}·{s['auth_label']}] {s['site']} | {s['title']}")
    if s["quote"]: print(f"      摘录：{s['quote'][:60]}")
