"""Streaming web interface for the Crew Ops Advisor."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Dict

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from crew_ops.openai_client import OpenAIClient
from crew_ops.reengineering_agent import ReengineeredCrewOpsAdvisor


load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "web" / "static"


async def homepage(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _run_query(question: str, queue: asyncio.Queue[Dict[str, Any]]) -> None:
    async def send(event: Dict[str, Any]) -> None:
        await queue.put(event)

    try:
        api_key = os.getenv("OPENAI_API_KEY", "")
        solver_model = os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        classifier_model = os.getenv("OPENAI_CLASSIFIER_MODEL", "").strip() or "gpt-4o-mini"
        checker_model = os.getenv("OPENAI_REENGINEERING_MODEL", "").strip() or "gpt-4o-mini"
        legal_model = os.getenv("OPENAI_LEGAL_MODEL", "").strip() or solver_model
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "crew_ops.mcp_server"],
            env=os.environ.copy(),
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                advisor = ReengineeredCrewOpsAdvisor(
                    session,
                    OpenAIClient(api_key=api_key, model=solver_model),
                    lambda: OpenAIClient(api_key=api_key, model=classifier_model),
                    lambda: OpenAIClient(api_key=api_key, model=checker_model),
                    lambda: OpenAIClient(api_key=api_key, model=legal_model),
                    event_handler=send,
                )
                await advisor.ask(question)
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

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(_run_query(question, queue))

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


routes = [
    Route("/", homepage),
    Route("/health", health),
    Route("/api/query", query, methods=["POST"]),
    Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(debug=False, routes=routes)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "crew_ops.web_app:app",
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
