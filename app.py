#!/usr/bin/env python3
"""谣侦 yaozhen —— FastAPI + 单请求流式 SSE（本地 & Vercel serverless 通用）。

启动（本地）：.venv/bin/python app.py   → http://127.0.0.1:8770
Vercel：api/index.py 直接 `from app import app` 作为 ASGI 入口。
"""
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from engine.run import run_check_stream
from engine import credentials, llm, search as search_mod

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

app = FastAPI(title="谣侦 yaozhen")


class CheckReq(BaseModel):
    kind: str = ""        # text | url | image；空则按 content 自动判
    content: str = ""
    image: str = ""       # data URI 或 base64（image 模式）


@app.post("/api/check")
async def check(req: CheckReq, request: Request):
    """单请求流式：POST 进来即持续吐 SSE 事件，最后一个是 done{report}。
    用户自带 key（BYOK）从请求头取，交给管线在其工作线程内使用（serverless 无状态友好）。"""
    content = (req.content or req.image or "").strip()
    if not content:
        async def empty():
            yield f"data: {json.dumps({'type':'error','title':'内容为空','detail':'请先粘贴要核查的内容'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")
    kind = req.kind
    if not kind:
        kind = "url" if content.startswith("http") else (
            "image" if content.startswith("data:image") or len(content) > 2000 else "text")
    ark_key = request.headers.get("x-ark-key", "").strip()
    search_key = request.headers.get("x-search-key", "").strip()

    def gen():
        try:
            for ev in run_check_stream(kind, content, ark_key, search_key):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa
            yield f"data: {json.dumps({'type':'error','icon':'⚠️','title':'核查中断','detail':str(e)[:120]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        iterate_in_threadpool(gen()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


class VerifyReq(BaseModel):
    ark_key: str = ""
    search_key: str = ""


@app.post("/api/verify-keys")
def verify_keys(req: VerifyReq):
    """轻量验证用户填的 key 是否可用（各发一个最小请求，不打印 key）。"""
    out: dict = {"ark": None, "search": None}
    credentials.use_keys(ark_key=req.ark_key, search_key=req.search_key)
    if req.search_key.strip():
        try:
            r = search_mod.search("人民日报", count=1, raise_on_error=True)
            out["search"] = "ok" if r else "empty"
        except Exception:
            out["search"] = "fail"
    if req.ark_key.strip():
        try:
            llm.chat_json_messages(
                [{"role": "user", "content": '只输出 JSON：{"ok":1}'}],
                max_tokens=10, timeout=40, retries=0)
            out["ark"] = "ok"
        except Exception:
            out["ark"] = "fail"
    credentials.clear()
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/static", StaticFiles(directory=WEB), name="web")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8770))
    print(f"谣侦 yaozhen v2 → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
