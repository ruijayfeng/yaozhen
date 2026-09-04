#!/usr/bin/env python3
"""谣侦 v2 主编排：输入 → 抽取主张 → 逐条 agent 核查 → 汇总报告 + 长辈卡片。

全程通过 emit(event) 推送结构化事件，供前端 SSE 实时渲染 agent 工作流。
事件类型：status | extract | claim_start | step | claim_done | done | error
"""
import base64
import time

from . import agent
from . import llm
from .pipeline import extract_claims, extract_claims_from_image
from .fetch import fetch_url

CARD_SYS = """你要为家庭群写一张「长辈版查证卡片」。给你若干条说法的核查结果（判决+大白话）。
严格输出 JSON：
{
 "headline":"这条别转 | 可以信 | 先别转",
 "said":"把原消息的说法用一句话中性概括，20-40字，开头不要加称呼",
 "facts":["给长辈看的大白话结论，每条≤28字，先说结论，用'不会/不能/可以/查无出处'等肯定语气，3-5条"],
 "closing":"一句温暖收尾，10-16字"
}
规则：全部谣言→headline=这条别转；全部属实→可以信；其余/含查无实据→先别转。
facts 里不要出现置信度、链接、英文；语气尊重，不说'你被骗了'。"""


def _emit(queue, ev):
    queue.append(ev)


def run_check(kind, content, events):
    """kind: text | url | image。content: 文本/URL/图片 data URI。返回 report dict。"""
    t0 = time.time()
    ev = lambda e: _emit(events, e)
    report = {"source": {"kind": kind}, "claims": [], "stats": {}}

    # ---- 1. 取正文 / 读图 ----
    if kind == "url":
        url = content.strip()
        ev({"type": "status", "icon": "🔗", "title": "正在抓取链接内容", "detail": url[:60]})
        title, text = fetch_url(url)
        report["source"].update({"title": title, "url": url, "chars": len(text)})
        ev({"type": "status", "icon": "📄", "title": f"已抓到《{title[:28]}》",
            "detail": f"正文 {len(text)} 字，准备拆说法"})
        claims, meta = extract_claims(text)
    elif kind == "image":
        ev({"type": "status", "icon": "🖼️", "title": "正在读图、识别文字", "detail": "多模态视觉理解中…"})
        # content 可能是 data URI 或裸 base64
        uri = content if content.startswith("data:") else f"data:image/png;base64,{content}"
        claims, ocr_text, meta = extract_claims_from_image(uri)
        report["source"]["ocr_text"] = ocr_text
        report["source"]["title"] = "（上传的截图/图片）"
        ev({"type": "status", "icon": "👁️", "title": f"读图完成，识别出 {len(ocr_text)} 字",
            "detail": "正在从中拆出可核查的说法"})
    else:
        report["source"]["title"] = "（粘贴的文本）"
        claims, meta = extract_claims(content)

    claims = claims[:6]
    report["stats"]["n_claims"] = len(claims)
    if not claims:
        ev({"type": "status", "icon": "🤔", "title": "没有找到可核查的事实主张",
            "detail": "这段内容里没有明显的健康/安全断言，换一段试试？"})
        report["overall"] = {"headline": "暂无可核查说法", "lead": "内容里没有发现可验证的断言。"}
        report["stats"]["elapsed_s"] = round(time.time() - t0, 1)
        return report

    ev({"type": "extract", "icon": "✂️",
        "title": f"拆出 {len(claims)} 条可核查说法",
        "detail": "开始逐条深度核查：模型自主搜索、打开原文、裁决矛盾"})

    # ---- 2. 逐条 agent 核查 ----
    tot_search = tot_open = n_auth = 0
    for i, c in enumerate(claims):
        q = c["claim"] if isinstance(c, dict) else c
        ev({"type": "claim_start", "index": i, "title": f"第 {i+1}/{len(claims)} 条：{q[:30]}"})
        try:
            verdict = agent.verify_claim_agentic(q, lambda e: ev(e), claim_index=i)
        except Exception as e:  # 单条核查失败不拖垮整份报告（网络/模型超时）
            verdict = {"rating": "查无实据", "confidence": 0.0,
                       "plain": "这条核查时网络或模型服务超时，没能拿到证据，建议先别转、稍后重试。",
                       "evidence": f"agent 核查异常：{str(e)[:120]}", "conflict": "", "claim": q,
                       "sources": [], "authority_hit": False,
                       "stats": {"searches": 0, "opened": 0, "results": 0, "elapsed_s": 0}}
        report["claims"].append(verdict)
        tot_search += verdict["stats"]["searches"]
        tot_open += verdict["stats"]["opened"]
        n_auth += len([s for s in verdict["sources"] if s["is_authoritative"]])
        ev({"type": "claim_done", "index": i,
            "rating": verdict["rating"], "title": q[:30]})
        time.sleep(0.2)

    # ---- 3. 汇总判决 ----
    ratings = [c["rating"] for c in report["claims"]]
    n_rumor = ratings.count("谣言") + ratings.count("夸大")
    n_true = ratings.count("属实")
    n_unknown = ratings.count("查无实据")
    if n_rumor == 0 and n_unknown == 0:
        headline, lead = "可以信", f"{n_true} 条说法均查到权威依据，没有发现谣言。"
    elif n_rumor >= max(1, len(claims) // 2):
        headline = "这条别转"
        lead = f"{len(claims)} 条说法中 {n_rumor} 条查实为谣言" + (f"，{n_unknown} 条查无实据" if n_unknown else "")
    elif n_rumor > 0:
        headline = "部分说法有问题"
        lead = f"{n_rumor} 条不实" + (f"，{n_unknown} 条查无实据，转发前请斟酌" if n_unknown else "，建议别整条转发")
    else:
        headline = "先别转"
        lead = f"{n_unknown} 条说法查无实据，权威源里找不到依据。"
    report["overall"] = {"headline": headline, "lead": lead,
                         "n_rumor": n_rumor, "n_true": n_true, "n_unknown": n_unknown}

    # ---- 4. 长辈版卡片文案 ----
    try:
        basis = "\n".join(
            f"{i+1}. 说法：{c['claim']}\n   判决：{c['rating']}\n   大白话：{c['plain']}"
            for i, c in enumerate(report["claims"]))
        card_obj, _ = llm.chat_json(CARD_SYS, f"核查结果：\n{basis}", max_tokens=900, timeout=120)
        report["elder_card"] = card_obj
    except Exception as e:  # noqa
        report["elder_card"] = {
            "headline": headline,
            "said": "（转发内容中的若干养生说法）",
            "facts": [c["plain"][:28] for c in report["claims"]][:4],
            "closing": "孩子们帮您查证过了 ☺",
        }

    report["stats"].update({
        "searches": tot_search, "opened": tot_open,
        "authority_sources": n_auth,
        "elapsed_s": round(time.time() - t0, 1),
    })
    return report
