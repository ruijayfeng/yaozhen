#!/usr/bin/env python3
"""谣侦批量评测：跑整链 run_check，输出每条判决供人工判读。
用法: .venv/bin/python scripts/eval_batch.py [--limit N]
结果存 scripts/eval_result.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.run import run_check

# 期望标签：rumor 谣言 | true 属实 | mixed 半真半假/夸大 | unverified 查无实据 | none 无主张
CASES = [
    ("味精加热超过100度会产生致癌物，吃了对身体有害。", "rumor"),
    ("隔夜菜含有亚硝酸盐，吃了一定致癌。", "rumor"),
    ("量子鞋垫能治糖尿病，三甲医院都在用。", "rumor"),
    ("吸烟会显著增加患肺癌的风险，这是有充分科学证据的。", "true"),
    ("接种新冠疫苗后留观30分钟，是为了及时发现急性过敏反应。", "true"),
    ("孩子发烧38.5度以上且明显不舒服，可以按说明书服用对乙酰氨基酚退烧。", "true"),
    ("每天喝8杯水能包治百病，感冒癌症都能喝好。", "mixed"),
    ("红酒泡洋葱能降血压，喝了就不用吃降压药了。", "mixed"),
    ("量子共振频率水可以调理人体磁场、疏通经络，长期喝能治百病。", "unverified"),
    ("今天天气真好，周末一起去公园散步吧，记得带伞。", "none"),
]

# 判定期望是否命中：rating 中文
RATING_OF = {"rumor": ["谣言", "夸大"], "true": ["属实"],
             "mixed": ["谣言", "夸大", "查无实据"], "unverified": ["查无实据"],
             "none": []}


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    results = []
    cases = CASES[:limit] if limit else CASES
    for i, (text, expect) in enumerate(cases, 1):
        events = []
        t0 = time.time()
        try:
            report = run_check("text", text, events)
            elapsed = time.time() - t0
        except Exception as e:
            print(f"\n[{i}/{len(cases)}] 💥 整链异常: {type(e).__name__}: {e}")
            results.append({"text": text, "expect": expect, "error": str(e)})
            continue

        st = report.get("stats", {})
        ov = report.get("overall", {})
        verdicts = report.get("claims", [])
        print(f"\n[{i}/{len(cases)}] ({elapsed:.0f}s, 搜{st.get('searches')} 开{st.get('opened')} 权威源{st.get('authority_sources')}) 期望:{expect}")
        print(f"   输入: {text[:42]}")
        if not verdicts:
            print(f"   ⚠️ 无主张 → overall: {ov.get('headline')} / {ov.get('lead','')[:40]}")
            results.append({"text": text, "expect": expect, "no_claims": True,
                            "overall": ov, "elapsed": round(elapsed, 1)})
            continue
        print(f"   总结论: {ov.get('headline')} — {ov.get('lead','')[:48]}")
        for c in verdicts:
            srcs = c.get("sources", [])
            levels = [f"{s.get('site','?')}({s.get('auth_label','')})" for s in srcs]
            print(f"   → [{c.get('rating')}|{c.get('confidence')}] {c.get('claim','')[:36]}")
            print(f"      权威命中:{c.get('authority_hit')} 信源卡:{len(srcs)} | {'; '.join(levels)[:88]}")
            print(f"      大白话: {c.get('plain','')[:60]}")
        # 期望命中判定
        got_ratings = [c.get("rating") for c in verdicts]
        if expect == "none":
            hit = not verdicts
        else:
            hit = any(r in RATING_OF[expect] for r in got_ratings)
        print(f"   {'✅ 命中期望' if hit else '❌ 偏离期望（'+','.join(got_ratings)+'）'}")
        results.append({
            "text": text, "expect": expect, "elapsed": round(elapsed, 1),
            "overall": ov, "hit": hit, "got_ratings": got_ratings,
            "claims": [{
                "claim": c.get("claim"), "rating": c.get("rating"),
                "confidence": c.get("confidence"), "authority_hit": c.get("authority_hit"),
                "plain": c.get("plain"), "evidence": c.get("evidence"),
                "n_sources": len(c.get("sources", [])),
                "sources": [{"site": s.get("site"), "auth": s.get("auth_label"),
                             "is_auth": s.get("is_authoritative"), "url": s.get("url")}
                            for s in c.get("sources", [])],
            } for c in verdicts],
            "stats": st,
        })

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 汇总
    print("\n" + "=" * 60)
    print("评测汇总：")
    for r in results:
        if r.get("error"):
            print(f"  💥 {r['text'][:24]} → 异常 {r['error'][:30]}")
        elif r.get("no_claims"):
            print(f"  {'✅' if r['expect']=='none' else '❌'} {r['text'][:24]} → 无主张 (期望{r['expect']})")
        else:
            mark = "✅" if r["hit"] else "❌"
            print(f"  {mark} {r['text'][:24]} → {r['got_ratings']} (期望{r['expect']})")
    print(f"\n结果已存 {out}")


if __name__ == "__main__":
    main()
