"""Vercel serverless entrypoint.

Vercel's Python runtime serves the ASGI application exposed as ``app`` here.
All routes are funnelled to this function by ``vercel.json``.
"""
from app.main import app  # noqa: F401  (re-exported for the Vercel runtime)
