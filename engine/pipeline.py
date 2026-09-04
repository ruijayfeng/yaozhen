#!/usr/bin/env python3
"""验真主管线：内容 → 主张抽取 → 逐条搜索对质 → 结构化报告。"""
import time

from . import llm
from . import search as search_mod

EXTRACT_SYS = """你是家庭群谣言鉴别助手。用户会给你一段中老年人在微信群/朋友圈/短视频里转发的内容（养生、健康、食品、生活常识类为主）。
你的任务：抽出其中**可被事实验证的主张**（claim），尤其是健康/安全相关的断言，如"X 致癌""X 能治 Y""吃 X 降血压""官方宣布 X"。
规则：
- 只抽事实性断言，不抽情绪句、号召句（"快转发""为了家人"）。
- 每条主张用一句通顺、中性、可搜索的陈述句表达，保留关键实体和数字。
- 最多抽 8 条最关键的；内容太短或没有可验证主张时返回空数组。
- 严格输出 JSON：{"claims": [{"claim": "...", "topic": "养生|食品|医疗政策|社会新闻|其他"}]}"""

VERDICT_SYS = """你是事实核查员。给你一条待核查的主张，以及联网搜索回来的真实网页结果（标题、来源、摘要、链接）。
你只能**依据这些搜索结果**判断，严禁使用你自己的内部知识；搜索结果不足以判断时，必须判"查无实据"。
判定等级：
- "谣言"：权威来源（政府/卫健/市监/疾控、权威媒体、辟谣平台、专业医生）明确否定，或多个可靠来源一致证伪。
- "属实"：权威来源明确证实。
- "夸大"：有部分依据但被绝对化/夸张（如"包治百病""100%"）。
- "查无实据"：搜索结果没有直接相关证据，或证据互相矛盾无法判定。
输出严格 JSON：
{"rating": "谣言|属实|夸大|查无实据",
 "confidence": 0.0-1.0,
 "explain": "一句大白话解释，给中老年人看，30-60字，先说结论再说依据",
 "sources": [{"title": "...", "url": "...", "site": "..."}],
 "authority_hit": true/false}
authority_hit 表示是否命中了政府/权威媒体/辟谣平台等权威来源。sources 最多列 3 条最相关的，必须是搜索结果里真实存在的链接，不许编造。"""


VISION_EXTRACT_SYS = """你是家庭群谣言鉴别助手。用户会给你一张图片，通常是：微信群聊截图、短视频（抖音/视频号）画面截图、朋友圈海报、养生科普长图、"官方通知"图片。
请完成两件事：
1. **完整识别图中所有文字**（OCR），包括标题、正文、字幕、水印、账号名，按阅读顺序转录，不要遗漏数字和日期。
2. 从识别出的文字里抽出**可被事实验证的主张**（健康/安全/政策类断言为主），规则同文字版：只抽事实断言，不抽情绪号召句，最多 8 条。
严格输出 JSON：
{"ocr_text": "图中识别到的全部文字（尽量完整）",
 "claims": [{"claim": "一句通顺可搜索的陈述句", "topic": "养生|食品|医疗政策|社会新闻|其他"}]}
如果图片里没有任何可验证主张（比如纯风景照），claims 返回空数组。"""


def extract_claims(text):
    obj, meta = llm.chat_json(
        EXTRACT_SYS,
        f"待鉴别内容：\n\n{text[:6000]}",
        max_tokens=1500,
    )
    claims = [c for c in obj.get("claims", []) if c.get("claim")]
    return claims, meta


def extract_claims_from_image(image_data_uri):
    """多模态读图：返回 (claims, ocr_text, meta)。"""
    obj, meta = llm.chat_json_vision(
        VISION_EXTRACT_SYS,
        "请识别这张图片中的全部文字，并抽出其中可验证的事实主张。",
        image_data_uri,
        max_tokens=2500,
    )
    claims = [c for c in obj.get("claims", []) if c.get("claim")]
    return claims, obj.get("ocr_text", ""), meta


def verify_claim(claim):
    """对一条主张：两轮搜索（辟谣向 + 事实向）→ LLM 判定。"""
    q = claim["claim"] if isinstance(claim, dict) else claim
    t0 = time.time()
    # 第一轮：辟谣/真相向，优先权威源
    r1 = search_mod.search(f"{q} 辟谣 真相", count=6)
    time.sleep(0.4)
    # 第二轮：事实向普通搜索
    r2 = search_mod.search(q, count=6)
    seen, results = set(), []
    for r in r1 + r2:
        if r["url"] and r["url"] not in seen:
            seen.add(r["url"])
            results.append(r)
    results = results[:8]

    if not results:
        return {"rating": "查无实据", "confidence": 0.0,
                "explain": "联网搜索没有返回结果，无法核实，建议先别转。",
                "sources": [], "authority_hit": False,
                "search_ms": int((time.time() - t0) * 1000), "n_results": 0}

    web_text = "\n\n".join(
        f"[{i+1}] 标题：{r['title']}\n来源：{r['site']}（{r['auth']}）\n链接：{r['url']}\n摘要：{r['summary']}"
        for i, r in enumerate(results))
    obj, meta = llm.chat_json(
        VERDICT_SYS,
        f"待核查主张：{q}\n\n搜索结果：\n{web_text}",
        max_tokens=1200,
    )
    # 安全兜底：sources 里的 url 必须真实存在于搜索结果
    real_urls = {r["url"] for r in results}
    obj["sources"] = [s for s in obj.get("sources", []) if s.get("url") in real_urls][:3]
    obj["search_ms"] = int((time.time() - t0) * 1000)
    obj["n_results"] = len(results)
    obj["tokens"] = meta
    return obj


def _verify_all(claims, report, progress=None):
    for i, c in enumerate(claims):
        if progress:
            progress("verify", f"正在核查第 {i+1}/{len(claims)} 条：{c['claim'][:24]}…")
        v = verify_claim(c)
        report["claims"].append({"claim": c["claim"], "topic": c.get("topic", ""), **v})
        time.sleep(0.3)

    ratings = [c["rating"] for c in report["claims"]]
    n_rumor = ratings.count("谣言") + ratings.count("夸大")
    if not claims:
        overall = "无可核查主张"
    elif n_rumor == 0 and "谣言" not in ratings:
        overall = "未发现谣言" if ratings.count("属实") >= 1 else "暂未发现明显问题"
    elif n_rumor >= max(1, len(claims) // 2):
        overall = "谣言高发，别转"
    else:
        overall = "部分说法有问题"
    report["overall"] = overall
    return report


def run_pipeline(text, source_title="", source_url="", progress=None):
    """完整管线（文字/链接正文）。progress: 可选回调 (stage, info)。"""
    report = {"source_title": source_title, "source_url": source_url,
              "claims": [], "stats": {}}
    t0 = time.time()

    if progress:
        progress("extract", "正在读内容、抽主张…")
    claims, ex_meta = extract_claims(text)
    report["stats"]["extract"] = ex_meta
    report["stats"]["n_claims"] = len(claims)

    _verify_all(claims, report, progress)
    report["stats"]["total_s"] = round(time.time() - t0, 1)
    return report


def run_pipeline_image(image_data_uri, source_title="（上传的图片）", progress=None):
    """视觉管线：图片 → 多模态 OCR+提主张 → 同一对质流程。"""
    report = {"source_title": source_title, "source_url": "",
              "claims": [], "stats": {}}
    t0 = time.time()

    if progress:
        progress("vision", "正在读图、识别文字…")
    claims, ocr_text, meta = extract_claims_from_image(image_data_uri)
    report["ocr_text"] = ocr_text
    report["stats"]["extract"] = meta
    report["stats"]["n_claims"] = len(claims)

    _verify_all(claims, report, progress)
    report["stats"]["total_s"] = round(time.time() - t0, 1)
    return report
