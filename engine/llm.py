#!/usr/bin/env python3
"""谣侦 yaozhen — 家庭群内容验真引擎。

调用方舟 Doubao-Seed-Evolving：
  endpoint: https://ark.cn-beijing.volces.com/api/plan/v3
  model:    ark-code-latest (路由到 doubao-seed-evolving)
关键事实：短 JSON 任务必须 thinking disabled，否则思考档跑 100s+ 且 reasoning tokens 撑爆 max_tokens。
"""
import json
import os
import threading
import time
import requests

from . import credentials

ARK_BASE = "https://ark.cn-beijing.volces.com/api/plan/v3"
MODEL = "ark-code-latest"

# 全局 LLM 串行锁：Ark plan 端点在并发请求下会间歇性 hang/限流，
# 串行化所有 LLM 调用以保证稳定（多任务时排队，前端有实时进度，可接受）。
_LLM_LOCK = threading.Lock()


def _load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file(os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/.env")
_load_env_file(os.path.expanduser("~/.openclaw/.env"))

# 凭证优先级：通用 ARK_API_KEY / ARK_API_BASE / ARK_MODEL，其次 Hermes 环境变量
API_KEY = (os.environ.get("ARK_API_KEY")
           or os.environ.get("HERMES_CUSTOM_ARK_CN_BEIJING_VOLCES_COM_API_KEY", ""))
if os.environ.get("ARK_API_BASE"):
    ARK_BASE = os.environ["ARK_API_BASE"].rstrip("/")
if os.environ.get("ARK_MODEL"):
    MODEL = os.environ["ARK_MODEL"]


class LLMError(RuntimeError):
    pass


def _call(messages, max_tokens=2000, timeout=120, retries=2):
    api_key = credentials.ark_key()
    if not api_key:
        raise LLMError("缺少方舟 LLM key：请在网页「设置」里填入 ARK key，或在服务端配置 ARK_API_KEY")
    payload = {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_err = None
    with _LLM_LOCK:  # 串行化：避免并发请求触发 Ark 端点 hang/限流
        for attempt in range(retries + 1):
            try:
                t0 = time.time()
                r = requests.post(f"{ARK_BASE}/chat/completions", headers=headers,
                                  json=payload, timeout=(10, timeout))
                r.raise_for_status()
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                obj = json.loads(content)
                return obj, {"latency_s": round(time.time() - t0, 1),
                             "total_tokens": usage.get("total_tokens", 0)}
            except Exception as e:  # noqa
                last_err = e
                time.sleep(2 * (attempt + 1))
    raise LLMError(f"LLM 调用失败: {last_err}")


def chat_json(system_prompt, user_prompt, max_tokens=2000, timeout=120, retries=2):
    """纯文本任务，返回严格 JSON。thinking disabled。"""
    return _call(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": user_prompt}],
        max_tokens=max_tokens, timeout=timeout, retries=retries)


def chat_json_messages(messages, max_tokens=2000, timeout=150, retries=2):
    """多轮消息（agent 工具循环用），返回严格 JSON。thinking disabled（快、稳）。"""
    return _call(messages, max_tokens=max_tokens, timeout=timeout, retries=retries)


def chat_json_vision(system_prompt, user_prompt, image_data_uri, max_tokens=2500, timeout=180):
    """多模态：图片 data URI（data:image/jpeg;base64,...）+ 文本，返回严格 JSON。"""
    return _call(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": [
             {"type": "text", "text": user_prompt},
             {"type": "image_url", "image_url": {"url": image_data_uri}},
         ]}],
        max_tokens=max_tokens, timeout=timeout)
