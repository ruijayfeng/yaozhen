#!/usr/bin/env python3
"""URL → 正文。公众号（mp.weixin.qq.com）实测 curl + 浏览器 UA 可抓全文。"""
import re
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _strip_tags(html):
    html = re.sub(r"<script[\s\S]*?</script>", " ", html)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_url(url):
    """返回 (title, text)。失败抛异常。"""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text

    title = ""
    m = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    if m:
        title = m.group(1)
    if not title:
        m = re.search(r'var\s+msg_title\s*=\s*[\'"](.+?)[\'"]\s*;', html)
        if m:
            title = m.group(1)
    if not title:
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        if m:
            title = m.group(1).strip()

    body = ""
    m = re.search(r'id="js_content"[^>]*>([\s\S]*?)(?:<script|<div\s+class="rich_media_tool)', html)
    if m:
        body = _strip_tags(m.group(1))
    if not body or len(body) < 200:
        m = re.search(r"<article[\s\S]*?</article>", html)
        if m:
            body = _strip_tags(m.group(0))
    if not body or len(body) < 200:
        body = _strip_tags(html)

    return title.strip(), body[:8000]
