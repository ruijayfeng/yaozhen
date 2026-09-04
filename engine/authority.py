#!/usr/bin/env python3
"""信源权威分级 —— 谣侦的「真实性」数据层基础。

判决只能依据真实检索到的网页；而网页不是平等的：
  A 权威：政府/卫健/疾控/市监、央媒、官方辟谣平台、官方科普
  B 可信：正规地方媒体、专业机构、大学/医院站点
  C 存疑：自媒体平台号、问答/种草站、个人订阅号（只作线索，不能一锤定音）
"""
import re
from urllib.parse import urlparse

# A 级：权威机构 / 央媒 / 官方辟谣科普
_AUTHORITATIVE_DOMAINS = [
    # 政府与官方机构
    "gov.cn", "nhc.gov.cn", "samr.gov.cn", "chinacdc.cn", "cdc.cn",
    "cac.gov.cn", "mca.gov.cn", "12315.cn",
    # 央媒
    "people.com.cn", "people.cn", "xinhuanet.com", "news.cn", "chinanews.com",
    "chinanews.com.cn", "cctv.com", "cntv.cn", "china.com.cn", "gmw.cn", "ce.cn",
    "cyol.com", "workercn.cn",
    # 官方辟谣 / 科普
    "piyao.org.cn", "kepuchina.cn", "crhtantan.com", "news.cctv.com",
    "science.org.cn", "cast.org.cn", "fact.qq.com",
]
# B 级：正规媒体 / 专业机构
_CREDIBLE_DOMAINS = [
    "thepaper.cn", "bjnews.com.cn", "nandu.cc", "ynet.com", "infzm.com",
    "caixin.com", "jiemian.com", "thecover.cn", "huanqiu.com", "sohu.com/a",
    "edu.cn", "org.cn", "hospital", "medline.gov", "who.int",
    # 专业医学科普平台
    "dxy.com", "dxy.cn", "guokr.com",
]
# C 级：自媒体 / UGC 平台（域名关键词命中即降权）
_SELF_MEDIA_HINTS = [
    "baijiahao.baidu.com", "sohu.com/a/", "mp.weixin.qq.com", "toutiao.com",
    "douyin.com", "xiaohongshu.com", "zhihu.com", "weibo.com", "bilibili.com",
    "163.com/dy/article", "k.sina.com.cn", "kuaishou.com", "baidu.com/tieba",
]

# 站点名里的权威信号（豆包搜索的 SiteName / AuthInfoDes 可能带这些）
_AUTHORITATIVE_NAME_HINTS = [
    "人民日报", "新华社", "央视", "中央电视台", "中国新闻网", "中新网", "光明网",
    "人民网", "科普中国", "辟谣平台", "卫生健康", "疾控", "市场监管", "政府网",
    "三甲医院", "人民医院", "附属医院", "科学院", "工程院", "中国互联网联合辟谣",
    "健康报", "生命时报", "北京协和", "华西医院",
]
_SELF_MEDIA_NAME_HINTS = [
    "搜狐号", "百家号", "网易号", "头条号", "企鹅号", "大鱼号", "自媒体",
    "个人主页", "微信公众号", "抖音号", "小红书", "知乎用户",
]


def _domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def classify(url="", site_name="", auth_desc=""):
    """返回 (level, label, is_authoritative)。
    level: 'A' | 'B' | 'C'；label: 中文徽章文案；is_authoritative: 能否作为判决硬依据。
    """
    host = _domain(url)
    name = f"{site_name} {auth_desc}"

    # C 级自媒体优先判定（具体路径/域名命中）
    for hint in _SELF_MEDIA_HINTS:
        if hint in url or (hint in host and "/" not in hint):
            return "C", "自媒体", False
    for hint in _SELF_MEDIA_NAME_HINTS:
        if hint in name:
            return "C", "自媒体", False

    # A 级权威
    if host.endswith(".gov.cn") or ".gov.cn" in host:
        return "A", "政府机构", True
    if host.endswith(".edu.cn"):
        return "A", "高校/科研", True
    for d in _AUTHORITATIVE_DOMAINS:
        if host == d or host.endswith("." + d.split("/")[0]):
            label = "官方辟谣平台" if "piyao" in d else (
                "官方科普" if "kepu" in d or "science" in d or "cast" in d else "权威媒体")
            return "A", label, True
    for hint in _AUTHORITATIVE_NAME_HINTS:
        if hint in name:
            if "医院" in hint or "疾控" in hint or "健康" in hint:
                return "A", "医疗机构", True
            return "A", "权威媒体", True

    # B 级可信
    for d in _CREDIBLE_DOMAINS:
        base = d.split("/")[0]
        if host == base or host.endswith("." + base):
            return "B", "正规媒体", False
    if re.search(r"医院|医学院|疾控|检验研究院|研究所|丁香医生|丁香园|腾讯医典", name):
        return "B", "专业机构", False

    # 无名小站 / 未知域名
    if not host:
        return "C", "来源未知", False
    return "C", "普通网页", False
