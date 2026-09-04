#!/usr/bin/env python3
"""豆包（火山引擎）联网搜索封装 —— 自包含，不依赖外部 skill。

凭证：环境变量 WEB_SEARCH_API_KEY（火山引擎搜索 Infinity API Key）。
      也会尝试从项目根 .env 或 ~/.openclaw/.env 读取（方便本地）。
开通：https://console.volcengine.com/search-infinity/api-key
官方文档：https://www.volcengine.com/docs/87772/2272953
"""
import json
import os

import requests

from . import credentials

INTERNAL_API_URL = "https://open.feedcoopapi.com/search_api/web_search"
TRAFFIC_TAG_HEADER = "X-Traffic-Tag"
TRAFFIC_TAG_VALUE = "skill_web_search_common"


def _load_env_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except OSError:
        pass


def _ensure_env():
    # 项目根 .env 优先，其次本地 ~/.openclaw/.env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _load_env_file(os.path.join(root, ".env"))
    _load_env_file(os.path.expanduser("~/.openclaw/.env"))


def _build_body(query, count=8, auth_level=0):
    body = {"Query": query, "SearchType": "web", "Count": count, "NeedSummary": True}
    if auth_level > 0:
        body["Filter"] = {"AuthInfoLevel": auth_level}
    return body


def search(query, count=8, auth_level=0, raise_on_error=False):
    """返回 [{title, site, auth, url, summary}]。默认失败返回空列表不抛异常；
    raise_on_error=True 时抛出（用于 key 连通性验证，区分「key 错」和「无结果」）。"""
    _ensure_env()
    api_key = (credentials.search_key() or "").strip()
    if not api_key:
        if raise_on_error:
            raise RuntimeError("缺少豆包搜索 key")
        print("[search] 未配置豆包搜索 key：请在网页「设置」填入，或服务端配置 WEB_SEARCH_API_KEY")
        return []
    try:
        body = _build_body(query, count=count, auth_level=auth_level)
        resp = requests.post(
            INTERNAL_API_URL,
            headers={
                "Content-Type": "application/json",
                TRAFFIC_TAG_HEADER: TRAFFIC_TAG_VALUE,
                "Authorization": f"Bearer {api_key}",
            },
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # 豆包对错误 key/额度问题返回 HTTP 200，但错误藏在 ResponseMetadata.Error
        meta_err = ((data.get("ResponseMetadata") or {}).get("Error")) if isinstance(data, dict) else None
        if meta_err:
            raise RuntimeError(
                f"搜索 API 错误 {meta_err.get('Code') or meta_err.get('CodeN')}: {meta_err.get('Message','')}")
        result_obj = data.get("Result") if isinstance(data, dict) else None
        # 豆包搜索偶发返回 Result:null（限流/空响应），必须兜底
        results = []
        for item in ((result_obj or {}).get("WebResults") or []):
            results.append({
                "title": item.get("Title", ""),
                "site": item.get("SiteName", ""),
                "auth": item.get("AuthInfoDes", ""),
                "url": item.get("Url", ""),
                "summary": (item.get("Summary") or item.get("Snippet") or "")[:600],
            })
        return results
    except Exception as e:  # noqa
        if raise_on_error:
            raise
        print(f"[search] 失败: {query!r} -> {e}")
        return []
