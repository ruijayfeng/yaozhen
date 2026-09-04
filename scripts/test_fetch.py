import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fetch import fetch_url
from engine.authority import classify

tests = [
    ("https://www.gov.cn/", "应 A（政府）"),
    ("https://www.chinanews.com.cn/", "应 A（央媒）"),
    ("https://mp.weixin.qq.com/s/dummy", "公众号域名（抓取会404，仅测分级）"),
]
for url, note in tests:
    print(f"URL: {url}  [{note}]")
    lvl, lbl, is_auth = classify(url=url, site_name="")
    print(f"  分级: level={lvl} label={lbl} authoritative={is_auth}")

# 真实抓取测 gov.cn 正文页（首页导航文字多，用一个具体栏目）
for url in ["https://www.gov.cn/", "https://www.chinanews.com.cn/"]:
    try:
        title, body = fetch_url(url)
        print(f"\n抓取 {url}: 标题={title[:40]!r} 正文 {len(body)} 字")
    except Exception as e:
        print(f"\n抓取 {url} 失败: {type(e).__name__}: {e}")
