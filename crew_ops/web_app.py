"""Streaming web interface for the Crew Ops Advisor."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict

from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from crew_ops.langchain_agent import close_agent, init_agent, stream_chat


load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "web" / "static"


async def homepage(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _run_query(question: str, thread_id: str, queue: asyncio.Queue[Dict[str, Any]]) -> None:
    async def send(event: Dict[str, Any]) -> None:
        await queue.put(event)

    try:
        await stream_chat(question, thread_id, send)
    except Exception as exc:
        await send({"type": "error", "message": str(exc)})
    finally:
        await queue.put({"type": "done"})


async def query(request: Request) -> StreamingResponse | JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "Request body must be valid JSON."}, status_code=400)

    question = str(payload.get("question", "")).strip()
    if not question:
        return JSONResponse({"error": "Please enter a question."}, status_code=400)
    if len(question) > 4000:
        return JSONResponse({"error": "Question is too long (maximum 4,000 characters)."}, status_code=400)

    thread_id = str(payload.get("session_id") or "").strip() or str(uuid.uuid4())

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(_run_query(question, thread_id, queue))

    async def stream() -> AsyncIterator[bytes]:
        try:
            while True:
                event = await queue.get()
                yield (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode()
                if event["type"] == "done":
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@asynccontextmanager
async def lifespan(_: Starlette) -> AsyncIterator[None]:
    await init_agent()
    try:
        yield
    finally:
        await close_agent()


routes = [
    Route("/", homepage),
    Route("/health", health),
    Route("/api/query", query, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(debug=False, routes=routes, lifespan=lifespan)


def run() -> None:
    import uvicorn

    reload = os.getenv("RELOAD", "").lower() in {"1", "true", "yes"}
    config = uvicorn.Config(
        "crew_ops.web_app:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8000")),
        reload=reload,
    )
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        # uvicorn defaults to ProactorEventLoop on Windows, but psycopg's async
        # driver (used by the Postgres checkpointer) requires a selector loop.
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        server.run()


if __name__ == "__main__":
    run()
