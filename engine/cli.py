#!/usr/bin/env python3
"""命令行测试：python -m engine.cli <公众号url>  或  echo "文本" | python -m engine.cli -"""
import json
import sys

from .fetch import fetch_url
from .pipeline import run_pipeline


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "-"

    if arg == "-":
        text = sys.stdin.read()
        title, url = "（直接粘贴的文本）", ""
    elif arg.startswith("http"):
        title, text = fetch_url(arg)
        url = arg
        print(f"[抓取] {title}  正文 {len(text)} 字\n", file=sys.stderr)
    else:
        print("用法: python -m engine.cli <url> 或 -（stdin）", file=sys.stderr)
        sys.exit(1)

    def progress(stage, info):
        print(f"[{stage}] {info}", file=sys.stderr)

    report = run_pipeline(text, source_title=title, source_url=url, progress=progress)

    print("\n" + "=" * 60)
    print(f"总结论：{report['overall']}（共核查 {len(report['claims'])} 条，耗时 {report['stats']['total_s']}s）")
    print("=" * 60)
    icon = {"谣言": "❌", "夸大": "⚠️", "属实": "✅", "查无实据": "❓"}
    for i, c in enumerate(report["claims"], 1):
        print(f"\n{i}. {icon.get(c['rating'], '·')} [{c['rating']}] {c['claim']}")
        print(f"   → {c['explain']}（权威来源命中：{c.get('authority_hit')}，置信度 {c.get('confidence')}）")
        for s in c.get("sources", [])[:2]:
            print(f"   出处：{s.get('site','')} {s.get('title','')[:30]} {s.get('url','')}")

    with open("/tmp/yaozhen_report.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[完整 JSON] /tmp/yaozhen_report.json", file=sys.stderr)


if __name__ == "__main__":
    main()
