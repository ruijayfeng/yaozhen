#!/usr/bin/env python3
"""谣侦 v2 —— FastAPI + SSE agent 事件流。
启动：.venv/bin/uvicorn app:app --port 8770   或  .venv/bin/python app.py
"""
import asyncio
import json
import os
import queue
import threading
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.run import run_check
from engine import credentials, llm, search as search_mod

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

app = FastAPI(title="谣侦 yaozhen")

JOBS = {}  # job_id -> {"events": list, "done": bool, "report": dict, "error": str|None}


class CheckReq(BaseModel):
    kind: str = ""        # text | url | image；空则按 content 自动判
    content: str = ""
    image: str = ""       # data URI 或 base64（image 模式）


def _worker(job_id, kind, content, ark_key, search_key):
    job = JOBS[job_id]
    try:
        # 请求级凭证（BYOK）：本工作线程内生效，用完随线程回收，不落盘
        credentials.use_keys(ark_key=ark_key, search_key=search_key)
        report = run_check(kind, content, job["events"])
        job["report"] = report
    except Exception as e:  # noqa
        import traceback
        traceback.print_exc()
        job["error"] = str(e)
        job["events"].append({"type": "error", "icon": "⚠️",
                              "title": "核查中断", "detail": str(e)[:120]})
    finally:
        credentials.clear()
    job["done"] = True


@app.post("/api/check")
def check(req: CheckReq, request: Request):
    content = (req.content or req.image or "").strip()
    if not content:
        return {"error": "内容为空"}
    kind = req.kind
    if not kind:
        kind = "url" if content.startswith("http") else ("image" if content.startswith("data:image") or len(content) > 2000 else "text")
    # 用户自带 key（BYOK），从请求头取；空则后端回落到环境变量
    ark_key = request.headers.get("x-ark-key", "").strip()
    search_key = request.headers.get("x-search-key", "").strip()
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "done": False, "report": None, "error": None}
    threading.Thread(target=_worker, args=(job_id, kind, content, ark_key, search_key),
                     daemon=True).start()
    return {"job_id": job_id}


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


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return StreamingResponse(iter([f"data: {json.dumps({'error': 'job not found'})}\n\n"]),
                                 media_type="text/event-stream")

    async def gen():
        sent = 0
        while True:
            while sent < len(job["events"]):
                ev = job["events"][sent]
                sent += 1
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if job["done"]:
                yield f"data: {json.dumps({'type': 'done', 'report': job.get('report'), 'error': job.get('error')}, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(0.35)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/static", StaticFiles(directory=WEB), name="web")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8770))
    print(f"谣侦 yaozhen v2 → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
