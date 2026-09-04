#!/usr/bin/env python3
"""灰色地带假阳性压测：专挑「听起来像谣言、其实有权威依据」的刁钻说法。
true 类是假阳性试金石（带"致癌/致病"句式但属实，绝不能判谣言）；
mixed 类是半真半假（应判夸大/谣言，但不能冤杀事实部分）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.run import run_check

CASES = [
    # —— 听起来像谣言、但其实有权威依据（绝不能误判！）——
    ("长期吃腌制的咸菜、咸鱼，会增加患胃癌和食管癌的风险。", "true",
     "中式咸鱼是WHO 1类致癌物，腌菜亚硝胺与消化道癌相关"),
    ("经常喝65度以上很烫的水、吃很烫的食物，会增加食管癌风险。", "true",
     "IARC把65℃以上烫饮列为2A类致癌物"),
    ("长期熬夜、昼夜节律颠倒，会增加患癌和心血管疾病的风险。", "true",
     "IARC将夜班工作列为2A类；睡眠紊乱与心血管病有据"),
    ("每天喝含糖饮料会增加肥胖、2型糖尿病和心血管病的风险。", "true",
     "强流行病学证据"),
    ("备孕和孕早期适量补充叶酸，能显著降低胎儿神经管畸形的风险。", "true",
     "全球公共卫生共识，强证据"),
    # —— 半真半假：有事实内核，但结论是伪科学/夸大 ——
    ("柠檬是碱性食物，喝柠檬水可以改变人体酸碱度，把酸性体质调成碱性，从而治好癌症。", "mixed",
     "酸碱体质说是伪科学，'喝柠檬水改变人体pH治癌'是谣言"),
    ("维生素C能预防感冒，每天大剂量吃维生素C片就不会感冒。", "mixed",
     "VitC或轻微缩短病程，但不能预防感冒（Cochrane），大剂量是夸大"),
    ("益生菌酸奶能调节肠道菌群、增强免疫力，老人小孩天天喝就不生病。", "mixed",
     "益生菌对部分肠道情况有益，但'增强免疫力不生病'是营销夸大"),
]

TRUE_OK = {"属实"}
MIXED_OK = {"谣言", "夸大", "查无实据"}  # 半真半假只要不判"属实"就算识别出问题


def main():
    results = []
    for i, (text, expect, note) in enumerate(CASES, 1):
        events = []
        t0 = time.time()
        try:
            report = run_check("text", text, events)
            elapsed = time.time() - t0
        except Exception as e:
            print(f"\n[{i}/{len(CASES)}] 💥 异常: {type(e).__name__}: {e}")
            results.append({"text": text, "expect": expect, "error": str(e)})
            continue
        verdicts = report.get("claims", [])
        ratings = [c.get("rating") for c in verdicts]
        st = report.get("stats", {})
        # 判定
        if expect == "true":
            # 假阳性 = 把属实说法判成了谣言/夸大
            bad = [r for r in ratings if r in ("谣言", "夸大")]
            hit = len(bad) == 0 and ("属实" in ratings)
            mark = "✅ 正确采信" if hit else ("🚨 假阳性！误判" if bad else "⚠️ 未采信")
        else:
            hit = any(r in MIXED_OK for r in ratings)
            mark = "✅ 识别出问题" if hit else "🚨 漏判（当成真的了）"
        print(f"\n[{i}/{len(CASES)}] ({elapsed:.0f}s 搜{st.get('searches')}) 期望:{expect} → {mark}")
        print(f"   说法: {text[:46]}")
        print(f"   科学基准: {note}")
        print(f"   判决: {ratings}  总结论: {report.get('overall',{}).get('headline')}")
        for c in verdicts:
            srcs = c.get("sources", [])
            auth = [s for s in srcs if s.get("is_authoritative")]
            print(f"     [{c.get('rating')}|{c.get('confidence')}] {c.get('claim','')[:34]}")
            print(f"       大白话: {c.get('plain','')[:64]}")
            print(f"       信源(权威{len(auth)}/{len(srcs)}): " + "; ".join(s.get("site","") for s in srcs[:3]))
        results.append({"text": text, "expect": expect, "note": note, "hit": hit,
                        "ratings": ratings, "mark": mark, "elapsed": round(elapsed,1),
                        "claims": [{"claim": c.get("claim"), "rating": c.get("rating"),
                                    "confidence": c.get("confidence"), "plain": c.get("plain"),
                                    "sources": [{"site": s.get("site"), "auth": s.get("auth_label"),
                                                 "is_auth": s.get("is_authoritative")} for s in c.get("sources",[])]}
                                   for c in verdicts]})

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_gray.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 64)
    print("灰色地带压测汇总：")
    n_fp = 0
    for r in results:
        if r.get("error"):
            print(f"  💥 {r['text'][:22]} → 异常"); continue
        flag = "🚨" if ("假阳性" in r.get("mark","") or "漏判" in r.get("mark","")) else ("⚠️" if "未采信" in r.get("mark","") else "✅")
        if "假阳性" in r.get("mark","") or "漏判" in r.get("mark",""): n_fp += 1
        print(f"  {flag} [{r['expect']:5s}] {r['text'][:26]} → {r['ratings']}")
    print(f"\n严重误判（假阳性/漏判）: {n_fp} 处")
    print(f"结果存 {out}")


if __name__ == "__main__":
    main()
