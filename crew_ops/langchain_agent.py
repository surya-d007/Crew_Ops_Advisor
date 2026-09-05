"""LangChain agent that answers Crew Ops Advisor questions using the dataset tools."""

from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Dict

from langchain.agents import create_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from crew_ops.tools import toolbox

SYSTEM_PROMPT = """You are the Crew Ops Advisor for the fictional dCortex Air dataset.
Use the supplied tools for dataset facts. Never invent crew, flights, times, costs,
rules, or availability. Fetch every piece of data needed before answering.
The dataset schedule covers 2026-09-14 through 2026-09-20, its snapshot is
2026-09-14T18:00:00Z, and all times are UTC. When a user omits the year for a date
inside this operating week, resolve it to 2026. Never substitute the current year.
Prefer a search tool when the user asks for all matching records; do not ask for IDs
when an available search tool can discover them. Date-range boundaries are inclusive.
For "how many" questions, prefer a dedicated count tool and report its count directly;
do not manually count records returned by a search tool when a count tool is available.
For rolling duty threshold questions, use search_crew_by_rolling_duty instead of
manually combining individual duty clocks and roster records.
For reserve coverage of a named aircraft duty, use assess_reserves_for_aircraft_duty.
Reserve-window eligibility uses the required report time (first departure minus 60
minutes), not the time when the sickness notification or phone call was received.

For an operational recommendation, inspect the affected pairing and candidate crew,
then verify role, status, aircraft rating, certifications, reserve date/window, base or
positioning, last rest, FDP, rolling 7-day duty hours, and rolling 28-day flight hours.
Explain calculations and cite IDs and rule IDs. Clearly label uncertainty if the basic
tools do not provide enough information. Treat risk scores as ranking signals, not legal
prohibitions. All times are UTC and all costs are INR unless the tools say otherwise.
Do not access or mention private held-out judging scenarios.
"""

DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:shahid0209@localhost:5432/postgres?sslmode=disable",
)
# MODEL_NAME = os.getenv("LANGCHAIN_MODEL", "google_genai:gemini-3.6-flash")
MODEL_NAME = os.getenv("LANGCHAIN_MODEL", "openai:gpt-5.1")
RECURSION_LIMIT = 100

AgentEventHandler = Callable[[Dict[str, Any]], Awaitable[None]]

_checkpointer_cm = None
_agent = None


async def init_agent() -> None:
    """Open the Postgres checkpointer and build the agent. Call once at startup."""
    global _checkpointer_cm, _agent
    if _agent is not None:
        return
    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(DB_URI)
    checkpointer = await _checkpointer_cm.__aenter__()
    await checkpointer.setup()
    _agent = create_agent(
        model=MODEL_NAME,
        tools=toolbox,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


async def close_agent() -> None:
    """Close the Postgres checkpointer opened by init_agent."""
    global _checkpointer_cm, _agent
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
    _checkpointer_cm = None
    _agent = None


def _tool_result_payload(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


async def stream_chat(question: str, thread_id: str, send: AgentEventHandler) -> None:
    """Run one turn of the agent, emitting the same event shapes the web UI expects."""
    if _agent is None:
        raise RuntimeError("LangChain agent is not initialized; call init_agent() first")

    await send({"type": "query_started", "question": question})
    round_number = 0
    config: Dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
    }

    async for chunk in _agent.astream(
        {"messages": [{"role": "user", "content": question}]},
        config=config,
        stream_mode="updates",
    ):
        for node_name, data in chunk.items():
            messages = data.get("messages", []) if isinstance(data, dict) else []

            if node_name == "model":
                round_number += 1
                await send({"type": "thinking", "round": round_number})
                for message in messages:
                    tool_calls = getattr(message, "tool_calls", None) or []
                    for call in tool_calls:
                        await send(
                            {
                                "type": "tool_started",
                                "id": call["id"],
                                "name": call["name"],
                                "arguments": call.get("args", {}),
                            }
                        )
                    if not tool_calls:
                        content = message.content if isinstance(message.content, str) else str(message.content)
                        await send({"type": "answer", "content": content.strip()})

            elif node_name == "tools":
                for message in messages:
                    await send(
                        {
                            "type": "tool_completed",
                            "id": message.tool_call_id,
                            "name": message.name,
                            "succeeded": getattr(message, "status", "success") != "error",
                            "result": _tool_result_payload(message.content),
                        }
                    )
