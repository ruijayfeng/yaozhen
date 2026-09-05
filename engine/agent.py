#!/usr/bin/env python3
"""谣侦 agent 核查循环 —— 模型自主决策的工具调用 loop。

与旧版写死 pipeline 的区别：
  模型自己决定「搜什么、要不要打开原文、信源打架找谁裁决、证据够不够下判决」。
工具（模型每轮只能返回一个 action）：
  search   — 豆包深度搜索，结果带回权威分级标签
  open_url — 打开搜索结果中的原文核对（url 必须真实来自搜索结果）
  judge    — 下判决（谣言/属实/夸大/查无实据），附证据卡
铁律：判决只能依据工具拿到的材料；sources/quote 经后端真实性质验，伪造即丢弃。
"""
import json
import re
import time

from . import authority
from . import llm
from . import search as search_mod
from . import vision

MAX_STEPS = 6          # 每条主张最多 6 个工具动作
MAX_OPEN = 2           # 最多打开 2 篇原文
FETCH_CHARS = 1800     # 打开原文给模型的字数

AGENT_SYS = """你是「谣侦」的事实核查 agent，为家庭群里的养生/健康传言做验真。
你有三个工具，每轮回复一个动作（严格 JSON）：

1. {"thought":"你这一步在想什么、为什么这么做（30字内）","action":"search","query":"搜索词"}
   —— 联网深度搜索。第一轮建议「<主张关键词> 辟谣 真相」；证据不够就换角度再搜
      （如机制原理、官方机构说法）。结果里每条都标了信源等级：
      [A] 政府/央媒/官方辟谣科普/三甲医院 = 权威，可作为判决硬依据；
      [B] 正规媒体/专业机构 = 可信参考；
      [C] 自媒体/百家号/搜狐号/抖音/知乎 = 只能当线索，不能一锤定音。

2. {"thought":"...","action":"open_url","url":"搜索结果里的真实 url"}
   —— 打开原文全文核对。两种情况务必用：①摘要互相矛盾、或权威源摘要不足以确认时；
      ②已锁定一篇 [A] 级权威源作为判决关键依据时——打开它，从正文逐字摘录支撑你判决的原话
      （正文原句比搜索摘要更硬，也能防断章取义）。最多 2 次。url 必须是搜索结果中出现过的，不许编造。

3. {"thought":"...","action":"judge",
    "rating":"谣言|属实|夸大|查无实据",
    "confidence":0.0-1.0,
    "plain":"给长辈看的大白话，30-60字，先给结论再说依据，语气尊重不吓人",
    "evidence":"给子女看的核查说明，80-150字，写明依据了哪些信源、如何裁决矛盾",
    "conflict":"若信源曾打架，一句话写明你如何裁决；没有则空字符串",
    "sources":[{"title":"","url":"","site":"","quote":"支持判决的原文原句，从摘要/正文中逐字摘录，不许改写编造"}],
    "authority_hit":true/false}

判决规则（极其重要）：
- 严禁使用你自己的内部知识，只能依据 search/open_url 拿到的材料。
- 「谣言/属实」必须有 [A] 级权威源明确支撑；只有 [C] 自媒体说法时，最多判「查无实据」。
- 搜遍权威源都找不到直接证据 → 判「查无实据」，这是诚实态，不是失败。
- [A] 与 [C] 说法矛盾时，以 [A] 为准，并在 conflict 里写明。
- sources 最多 3 条，url 必须真实存在于工具结果；quote 必须逐字摘自材料，摘不到就留空。
- 通常 2-4 次搜索（+ 1 次 open_url 核对权威原文）证据就够了；动作总数不超过 6 次，最后必须 judge。
- 只要手里有 [A] 级权威源且一次原文都没打开过，judge 前请先 open_url 其中最关键的一篇核对正文。
严格只输出一个 JSON 对象，不要输出其他文字。"""


def _classify_results(results):
    for r in results:
        level, label, is_auth = authority.classify(
            r.get("url", ""), r.get("site", ""), r.get("auth", ""))
        r["level"] = level
        r["auth_label"] = label
        r["is_authoritative"] = is_auth
    return results


def _format_results(results):
    lines = []
    for i, r in enumerate(results):
        lines.append(
            f"{i+1}. [{r['level']}·{r['auth_label']}] {r['title']}\n"
            f"   来源：{r['site']} {('(' + r['auth'] + ')') if r.get('auth') else ''}\n"
            f"   摘要：{r['summary']}\n   链接：{r['url']}")
    return "\n".join(lines)


def _safe_json(text):
    """从模型输出里容错抽 JSON。"""
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def verify_claim_agentic(claim, emit, claim_index=0, visual_ctx=None):
    """对一条主张跑 agent 循环。
    emit(event_dict) 推送时间线事件。返回证据卡 + 判决 dict。
    visual_ctx: 若给（dict），表示这是图片「假借权威」核查，使用视觉专用系统提示词，
                并在判决上挂视觉红旗。键：purported_source / visual_flags / image_note。
    """
    t0 = time.time()
    sys_prompt = vision.IMPERSONATION_SYS if visual_ctx else AGENT_SYS
    user_head = ("待核查的是一张冒充权威的图片：\n"
                 f"- 图片自称来自：{visual_ctx.get('purported_source','')}\n"
                 f"- 画面描述：{visual_ctx.get('image_note','')}\n"
                 f"- 视觉可疑信号：{('；'.join(visual_ctx.get('visual_flags',[])) or '无明显信号')}\n\n"
                 "请联网核实该机构是否真的发布过这条通知，以及图中说法的真伪。先搜索，证据充分后 judge。") \
        if visual_ctx else \
        f"待核查主张：{claim}\n\n开始核查。先搜索，证据充分后 judge。"
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_head},
    ]
    seen_results = []          # 全部搜索结果（去重）
    seen_urls = set()
    fetched = {}               # url -> 正文摘录
    stats = {"searches": 0, "opened": 0, "results": 0}

    def tool_result(msg):
        messages.append({"role": "user", "content": msg})

    final = None
    for step in range(MAX_STEPS):
        obj, meta = llm.chat_json_messages(messages, max_tokens=1400, timeout=90, retries=1)
        messages.append({"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)})
        thought = (obj.get("thought") or "").strip()
        action = obj.get("action", "")

        if action == "search":
            q = (obj.get("query") or "").strip()
            if not q:
                tool_result("【工具错误】query 为空，请重新给出动作。")
                continue
            stats["searches"] += 1
            emit({"type": "step", "icon": "🔍",
                  "title": f"深度搜索「{q[:34]}」",
                  "detail": thought, "tag": "", "tag_text": ""})
            results = _classify_results(search_mod.search(q, count=7))
            fresh = []
            for r in results:
                if r["url"] and r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    seen_results.append(r)
                    fresh.append(r)
            stats["results"] = len(seen_results)
            n_a = sum(1 for r in fresh if r["level"] == "A")
            n_c = sum(1 for r in fresh if r["level"] == "C")
            warn = bool(re.search(r"分歧|矛盾|打架|不一致", thought))
            emit({"type": "step", "icon": "📊",
                  "title": f"返回 {len(fresh)} 条新结果" + (f"（权威 {n_a} · 自媒体 {n_c}）" if fresh else "（无新结果）"),
                  "detail": "豆包深度搜索 · 信源已自动分级",
                  "tag": "warn" if warn else ("ok" if n_a else ""),
                  "tag_text": "发现信源分歧" if warn else ("命中权威源" if n_a else "")})
            tool_result("【search 结果】\n" + (_format_results(fresh) if fresh else "（本次没有新结果，换个关键词试试）"))

        elif action == "open_url":
            url = (obj.get("url") or "").strip()
            if url not in seen_urls:
                tool_result(f"【工具错误】{url} 不在搜索结果中，不能打开。请从结果里选真实链接。")
                continue
            if stats["opened"] >= MAX_OPEN:
                tool_result("【工具提示】打开原文次数已达上限，请基于现有材料 judge。")
                continue
            stats["opened"] += 1
            src = next((r for r in seen_results if r["url"] == url), {})
            emit({"type": "step", "icon": "📖",
                  "title": f"打开原文核对：{src.get('site') or url[:30]}",
                  "detail": thought, "tag": "blue", "tag_text": "读取全文"})
            try:
                from .fetch import fetch_url
                title, text = fetch_url(url)
                excerpt = text[:FETCH_CHARS]
                fetched[url] = excerpt
                tool_result(f"【open_url 结果】{url}\n标题：{title}\n正文摘录：\n{excerpt}")
            except Exception as e:  # noqa
                tool_result(f"【open_url 结果】{url} 打开失败：{e}（请基于摘要判断）")

        elif action == "judge":
            final = obj
            break
        else:
            tool_result("【工具错误】action 必须是 search / open_url / judge 之一。")

    # 循环耗尽仍未 judge → 强制补一次判决
    if not final:
        messages.append({"role": "user", "content":
            "动作次数已用完。请现在立刻基于已有材料 judge；材料不足以判定就 rating=查无实据。"})
        obj, _ = llm.chat_json_messages(messages, max_tokens=1400, timeout=90, retries=1)
        final = obj if obj.get("action") == "judge" or obj.get("rating") else None
        if not final:
            final = {"rating": "查无实据", "confidence": 0.0,
                     "plain": "核查过程中没能获得足够证据，建议先别转。",
                     "evidence": "达到工具动作上限仍未形成判决，保守处理。",
                     "conflict": "", "sources": [], "authority_hit": False}

    # ---------- 后验真：证据卡清洗（防幻觉） ----------
    verdict = {
        "rating": final.get("rating", "查无实据"),
        "confidence": float(final.get("confidence", 0) or 0),
        "plain": (final.get("plain") or "").strip(),
        "evidence": (final.get("evidence") or "").strip(),
        "conflict": (final.get("conflict") or "").strip(),
        "claim": claim,
        "stats": {"searches": stats["searches"], "opened": stats["opened"],
                  "results": stats["results"], "elapsed_s": round(time.time() - t0, 1)},
    }
    if verdict["rating"] not in ("谣言", "属实", "夸大", "查无实据"):
        verdict["rating"] = "查无实据"

    by_url = {r["url"]: r for r in seen_results}
    evidence_cards = []
    for s in (final.get("sources") or [])[:3]:
        url = (s.get("url") or "").strip()
        if url not in by_url:        # 幻觉链接直接丢弃
            continue
        r = by_url[url]
        quote = (s.get("quote") or "").strip()
        # 引文必须真实出现在摘要/已抓正文里，否则丢弃（不许改写冒充原文）
        corpus = r.get("summary", "") + "\n" + fetched.get(url, "")
        if quote and quote not in corpus:
            quote = ""
        evidence_cards.append({
            "title": r.get("title") or s.get("title", ""),
            "url": url,
            "site": r.get("site", ""),
            "auth_label": r["auth_label"],
            "level": r["level"],
            "is_authoritative": r["is_authoritative"],
            "quote": quote[:120],
        })
    # 证据卡按权威等级排序 A>B>C；已有 ≥2 条 A/B 级时，C 级自媒体不进证据链（只在线索层起过作用）
    order = {"A": 0, "B": 1, "C": 2}
    ab = [c for c in evidence_cards if c["level"] in ("A", "B")]
    c_cards = [c for c in evidence_cards if c["level"] == "C"]
    evidence_cards = sorted((ab if len(ab) >= 2 else ab + c_cards),
                            key=lambda c: order.get(c["level"], 3))[:3]
    verdict["sources"] = evidence_cards
    verdict["authority_hit"] = any(c["is_authoritative"] for c in evidence_cards)

    # 数据层约束：无权威源时，任何否定/肯定判决都不成立（含「夸大」，防止仅凭自媒体误伤真消息）
    if verdict["rating"] in ("谣言", "属实", "夸大") and not verdict["authority_hit"]:
        verdict["rating"] = "查无实据"
        verdict["confidence"] = 0.0
        verdict["plain"] = "没有查到权威来源能证实或证伪这个说法，建议先别转。"
    if verdict["rating"] == "查无实据":
        verdict["confidence"] = 0.0
    verdict["confidence"] = round(min(1.0, max(0.0, verdict["confidence"])), 2)

    # 视觉鉴伪：挂上画面红旗与冒充来源（供前端「视觉鉴伪」段展示）
    if visual_ctx:
        verdict["visual"] = True
        verdict["purported_source"] = visual_ctx.get("purported_source", "")
        verdict["visual_flags"] = visual_ctx.get("visual_flags", [])
        verdict["claim"] = f"图片署名「{verdict['purported_source']}」发布通知" if verdict.get("purported_source") else claim

    # 判决事件
    icon = {"谣言": "🚫", "属实": "✅", "夸大": "⚠️"}.get(verdict["rating"], "❓")
    emit({"type": "step", "icon": icon,
          "title": f"判决：{verdict['rating']}" + (f"（置信度 {int(verdict['confidence']*100)}%）" if verdict["rating"] != "查无实据" else ""),
          "detail": verdict["plain"][:60],
          "tag": "blue" if verdict["rating"] == "查无实据" else "ok",
          "tag_text": "诚实态" if verdict["rating"] == "查无实据" else "已下判决"})
    return verdict
