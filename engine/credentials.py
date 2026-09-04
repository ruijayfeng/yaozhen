#!/usr/bin/env python3
"""请求级凭证上下文（BYOK）。

开源模式下，用户在网页「设置」里填自己的火山引擎 key，浏览器随请求捎来；
后端在处理该请求的工作线程里用 use_keys() 临时设置，调用结束即随线程回收，
不落盘、不进日志。环境变量里配置的 key 始终作为兜底（自部署家用模式）。
"""
import threading
import os

_ctx = threading.local()

KEY_ENV = {
    "ark": "HERMES_CUSTOM_ARK_CN_BEIJING_VOLCES_COM_API_KEY",
    "search": "WEB_SEARCH_API_KEY",
}


def use_keys(ark_key=None, search_key=None):
    """在当前工作线程设置本次请求使用的 key（传 None/空则不覆盖）。"""
    if ark_key:
        _ctx.ark = ark_key.strip()
    if search_key:
        _ctx.search = search_key.strip()


def clear():
    """显式清空（线程复用时保险）。"""
    for attr in ("ark", "search"):
        if hasattr(_ctx, attr):
            delattr(_ctx, attr)


def ark_key():
    """本次请求的方舟 LLM key：优先请求级，其次通用 ARK_API_KEY，最后 Hermes 变量。"""
    return (getattr(_ctx, "ark", None)
            or os.environ.get("ARK_API_KEY")
            or os.environ.get(KEY_ENV["ark"], ""))


def search_key():
    """本次请求的豆包搜索 key：优先请求级，其次环境变量。"""
    return getattr(_ctx, "search", None) or os.environ.get(KEY_ENV["search"], "")
