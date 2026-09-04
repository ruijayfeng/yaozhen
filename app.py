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

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.run import run_check

BASE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(BASE, "web")

app = FastAPI(title="谣侦 yaozhen")

JOBS = {}  # job_id -> {"events": list, "done": bool, "report": dict, "error": str|None}


class CheckReq(BaseModel):
    kind: str = ""        # text | url | image；空则按 content 自动判
    content: str = ""
    image: str = ""       # data URI 或 base64（image 模式）


def _worker(job_id, kind, content):
    job = JOBS[job_id]
    try:
        report = run_check(kind, content, job["events"])
        job["report"] = report
    except Exception as e:  # noqa
        import traceback
        traceback.print_exc()
        job["error"] = str(e)
        job["events"].append({"type": "error", "icon": "⚠️",
                              "title": "核查中断", "detail": str(e)[:120]})
    job["done"] = True


@app.post("/api/check")
def check(req: CheckReq):
    content = (req.content or req.image or "").strip()
    if not content:
        return {"error": "内容为空"}
    kind = req.kind
    if not kind:
        kind = "url" if content.startswith("http") else ("image" if content.startswith("data:image") or len(content) > 2000 else "text")
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"events": [], "done": False, "report": None, "error": None}
    threading.Thread(target=_worker, args=(job_id, kind, content), daemon=True).start()
    return {"job_id": job_id}


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
