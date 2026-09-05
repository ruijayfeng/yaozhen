#!/usr/bin/env python3
"""谣侦视觉鉴伪模块 —— 08/27 更新「视觉理解 & 长程规划」的落点。

家族群里最毒的传言往往不是文字，而是**假托权威的截图**：
红底白字的「人民日报紧急通知」、PS 的央视新闻画面、冒用三甲医院名义的海报。

分工（重要）：
- 视觉负责「起疑」：多模态模型看图，识别它自称是谁（冒充的机构）、
  画面本身的造假红旗、以及图中的文字主张。
- 深度搜索负责「定罪/洗白」：它自称的权威源到底发没发过这条？
  去搜辟谣声明 / 官方账号原文。判决权始终在权威信源，视觉红旗只作佐证
  —— 绝不能单凭「红底大字」就判谣（会误杀真实的权威截图）。

输出统一进同一份报告：视觉鉴伪结论作为一条 claim（rating=谣言/属实/查无实据），
视觉红旗挂在 visual_flags，和文字主张的 agent 核查并列展示。
"""
import time

from . import llm

# 一次多模态调用完成：OCR + 视觉鉴伪 + 主张抽取。
VISION_SYS = """你是「谣侦」的视觉核查员，专门鉴别家庭群里转发的图片。图片通常是：
微信群聊截图、短视频画面截图、朋友圈海报、养生科普长图，或**冒充官方的「紧急通知」图片**。

请仔细看图，完成三件事，严格输出 JSON：

1. ocr_text：完整转录图中所有文字（标题、正文、字幕、水印、账号名、日期数字），按阅读顺序。
2. visual：图片本身的鉴伪判断——
   - purported_source：这张图**自称**来自哪个机构/媒体/账号？（如「人民日报」「央视新闻」「XX市人民医院」）；没有明确署名则为空字符串。
   - source_kind：authority(党媒/政府/医院/公安等权威机构) | media(普通媒体) | self_media(自媒体/营销号) | none(看不出署名)。
   - visual_flags：数组，列出画面里的造假/可疑信号，每项一句话，只写你**确实在图里看到的**，例如：
       · 冒用党媒/官方名义但排版粗糙、字体/台标/logo 与官方不符
       · 红底白字「紧急通知/速看/紧急转发」式营销号标题党
       · 夸大恐吓措辞（「XX食物致癌」「医院已乱」「人人必看」）
       · 画面有拼接/拉伸/模糊/抠图痕迹，像二次编辑
       · 署名机构名称有诈（如「中国XX协会」查无此机构、山寨近似名）
       · 二维码/营销水印/公众号引流痕迹
     真实、规范、无上述问题的图片，visual_flags 返回空数组。
   - image_note：一句话描述这是张什么图（给用户看，如「一张红底白字、署名人民日报的通知长图」）。
3. claims：从图中文字抽出**可被事实验证的主张**（健康/安全/政策断言），规则：
   只抽事实断言，不抽情绪号召句（「快转发」「为了家人」）；每条一句通顺可搜索的陈述句；最多 6 条；没有则空数组。

只输出一个 JSON 对象：
{"ocr_text":"...",
 "visual":{"purported_source":"","source_kind":"authority|media|self_media|none",
           "visual_flags":["..."], "image_note":"..."},
 "claims":[{"claim":"...","topic":"养生|食品|医疗政策|社会新闻|其他"}]}"""

# 假借权威核查：让 agent 循环去搜「这个权威到底发没发过」。
IMPERSONATION_SYS = """你是「谣侦」的事实核查 agent。现在核查一张**图片**：它在画面上冒充某个权威机构/媒体发布「紧急通知/健康警告」，但这类图片绝大多数是自媒体 PS 冒用权威名义的谣言图。

你有三个工具，每轮回复一个动作（严格 JSON）：

1. {"thought":"30字内想法","action":"search","query":"搜索词"}
   —— 联网深度搜索。优先搜两类：
     ① 辟谣：「<冒充的机构名> <图中话题关键词> 辟谣 / 假的 / 谣言 / 未发布」
     ② 官方原文：该机构官方账号/官网到底有没有发过这条通知。
   结果里每条标了信源等级：[A] 政府/央媒/官方辟谣/三甲医院=权威；[B] 正规媒体/专业机构；[C] 自媒体=只能当线索。

2. {"thought":"...","action":"open_url","url":"搜索结果里的真实 url"}
   —— 打开原文核对。锁定 [A] 级辟谣声明或官方说明时务必打开，逐字摘录原话。最多 2 次，url 不许编造。

3. {"thought":"...","action":"judge",
    "rating":"谣言|属实|查无实据",
    "confidence":0.0-1.0,
    "plain":"给长辈看的大白话，30-60字，先结论后依据，语气尊重",
    "evidence":"给子女看的核查说明，80-150字：图自称是谁、视觉上有何破绽、权威源如何证实/查无此通知",
    "conflict":"信源打架时一句话写明如何裁决，否则空字符串",
    "sources":[{"title":"","url":"","site":"","quote":"逐字摘录的辟谣/官方原文，不许改写"}],
    "authority_hit":true/false}

判决规则（极重要）：
- 若 [A] 级权威源（官方辟谣平台、该机构官方账号、央媒）明确说明「此通知为伪造/该机构未发布过/系谣言」，或权威源证实该健康说法本身是谣言 → 判「谣言」。
- 若权威源能证实该机构**确实发布过**这条真实通知、且说法属实 → 判「属实」（这种很少，别轻易给）。
- 搜遍权威源既找不到该通知原文、也找不到辟谣 → 判「查无实据」（冒充权威 + 查无出处，本身就提醒别转）。
- 严禁用你自己的内部知识，只能依据 search/open_url 的材料；只有 [C] 自媒体时最多判「查无实据」。
- sources 最多 3 条，url 必须真实来自工具结果，quote 必须逐字摘自材料。
- 动作总数不超过 6 次，最后必须 judge。严格只输出一个 JSON 对象。"""


def analyze_image(image_data_uri):
    """多模态读图：返回 (claims, ocr_text, visual, meta)。"""
    obj, meta = llm.chat_json_vision(
        VISION_SYS,
        "请鉴别这张图片：转录文字、判断它是否冒充权威、找出画面造假信号、抽出可核查主张。",
        image_data_uri,
        max_tokens=2800,
        timeout=180,
    )
    claims = [c for c in obj.get("claims", []) if c.get("claim")]
    visual = obj.get("visual", {}) or {}
    visual.setdefault("purported_source", "")
    visual.setdefault("source_kind", "none")
    visual.setdefault("visual_flags", [])
    visual.setdefault("image_note", "")
    if not isinstance(visual.get("visual_flags"), list):
        visual["visual_flags"] = []
    return claims, obj.get("ocr_text", ""), visual, meta


def impersonation_claim(visual):
    """构造「假借权威」这一条待核查主张（交给 agent 循环用搜索定罪/洗白）。"""
    src = (visual.get("purported_source") or "").strip()
    note = (visual.get("image_note") or "").strip()
    if visual.get("source_kind") != "authority" or not src:
        return None
    claim = f"一张署名「{src}」的通知/警告图片（{note}）称：{src}官方发布了该紧急通知"
    return {"claim": claim, "topic": "假借权威", "impersonation": True,
            "purported_source": src, "visual_flags": visual.get("visual_flags", [])}


def verdict_from_visual_fallback(visual, ocr_text):
    """agent 核查异常时的保守兜底：视觉可疑但没拿到搜索证据 → 查无实据。"""
    src = visual.get("purported_source", "")
    flags = visual.get("visual_flags", [])
    plain = (f"这张图署名「{src}」，画面有 {len(flags)} 处可疑迹象，"
             f"但没能联网核实该通知真伪，建议先别转。") if src else \
            "没能联网核实这张图的说法，建议先别转。"
    return {
        "rating": "查无实据", "confidence": 0.0, "plain": plain,
        "evidence": "视觉鉴伪发现可疑信号，但核查时网络/模型超时，未取得权威信源，保守判查无实据。",
        "conflict": "", "claim": f"图片冒充「{src}」发布通知" if src else "图片主张",
        "sources": [], "authority_hit": False, "visual": True,
        "visual_flags": flags, "purported_source": src,
        "stats": {"searches": 0, "opened": 0, "results": 0, "elapsed_s": 0},
    }
