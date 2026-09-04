"""Vercel serverless 入口：把根目录的 FastAPI app 暴露为 ASGI 应用。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app  # noqa: E402,F401
