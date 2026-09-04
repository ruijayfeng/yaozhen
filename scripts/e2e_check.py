#!/usr/bin/env python3
"""端到端：POST /api/check → 消费 SSE → 打印事件流 + 落盘 report.json。"""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8770"
text = sys.argv[1] if len(sys.argv) > 1 else "味精加热超过100度会致癌？隔夜菜含亚硝酸盐吃了一定致癌？"

req = urllib.request.Request(BASE + "/api/check",
    data=json.dumps({"kind": "text", "content": text}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
job = json.loads(urllib.request.urlopen(req, timeout=30).read())
print("job:", job["job_id"])

t0 = time.time()
report = None
with urllib.request.urlopen(f"{BASE}/api/stream/{job['job_id']}", timeout=600) as r:
    for raw in r:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:].strip())
        typ = ev.get("type")
        if typ == "done":
            report = ev.get("report")
            err = ev.get("error")
            print(f"\n[done in {time.time()-t0:.0f}s] error={err}")
            break
        if typ in ("status", "extract", "claim_start"):
            print(f"\n── {ev.get('icon','')} {ev.get('title','')}")
        elif typ == "step":
            tag = f" [{ev.get('tag_text')}]" if ev.get("tag_text") else ""
            print(f"   {ev.get('icon','')} {ev.get('title','')}{tag}")

if report:
    with open("/Users/jayfeng/Developer/yaozhen/scripts/last_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    o = report.get("overall", {})
    print(f"\n总结论：{o.get('headline')} — {o.get('lead')}")
    for c in report.get("claims", []):
        print(f"  [{c['rating']}|{c.get('confidence')}] {c['claim'][:30]} → 证据卡 {len(c['sources'])} 张"
              f"（权威 {sum(1 for s in c['sources'] if s['is_authoritative'])}）")
    print("长辈卡片：", json.dumps(report.get("elder_card", {}), ensure_ascii=False)[:300])
    print("\nreport 已存 scripts/last_report.json")
