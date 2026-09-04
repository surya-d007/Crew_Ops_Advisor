"""Tool-calling agent that connects an LLM to the MCP dataset server."""

from __future__ import annotations

import json
import sys
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from mcp import ClientSession



class ChatClient(Protocol):
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]: ...


AgentEventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


SYSTEM_PROMPT = """You are the Crew Ops Advisor for the fictional dCortex Air dataset.
Use the supplied MCP tools for dataset facts. Never invent crew, flights, times, costs,
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


def _ollama_tools(mcp_tools: Any) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        }
        for tool in mcp_tools.tools
    ]


def _tool_result_text(result: Any) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    return json.dumps({"is_error": bool(result.isError)}, ensure_ascii=False)


class CrewOpsAgent:
    def __init__(
        self,
        session: ClientSession,
        llm: ChatClient,
        max_rounds: int = 40,
        verbose: bool = False,
        event_handler: Optional[AgentEventHandler] = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.max_rounds = max_rounds
        self.verbose = verbose
        self.event_handler = event_handler
        self.messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.tools: List[Dict[str, Any]] = []

    async def _emit(self, event_type: str, **data: Any) -> None:
        if self.event_handler is not None:
            await self.event_handler({"type": event_type, **data})

    def _trace(self, heading: str, value: Any = None) -> None:
        if not self.verbose:
            return
        print(f"\n[trace] {heading}", file=sys.stderr, flush=True)
        if value is None:
            return
        rendered = value if isinstance(value, str) else json.dumps(
            value, indent=2, ensure_ascii=False, default=str
        )
        print(rendered, file=sys.stderr, flush=True)

    async def initialize(self) -> None:
        listed = await self.session.list_tools()
        self.tools = _ollama_tools(listed)
        self._trace("MCP tools discovered", [tool["function"]["name"] for tool in self.tools])

    async def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        await self._emit("query_started", question=question)

        for round_number in range(1, self.max_rounds + 1):
            self._trace(f"LLM round {round_number} started")
            await self._emit("thinking", round=round_number)
            assistant_message = await self.llm.chat(self.messages, self.tools)
            self.messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                self._trace("LLM final response ready")
                answer = assistant_message.get("content", "").strip()
                await self._emit("answer", content=answer)
                return answer

            for tool_index, tool_call in enumerate(tool_calls, start=1):
                function = tool_call.get("function", {})
                name = function.get("name", "")
                tool_call_id = tool_call.get("id")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)

                self._trace(f"Calling MCP tool: {name}")
                self._trace("Tool input", arguments)
                event_id = tool_call_id or f"round-{round_number}-tool-{tool_index}"
                await self._emit(
                    "tool_started",
                    id=event_id,
                    name=name,
                    arguments=arguments,
                )

                succeeded = True
                try:
                    result = await self.session.call_tool(name, arguments)
                    content = _tool_result_text(result)
                    succeeded = not bool(result.isError)
                except Exception as exc:
                    content = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    succeeded = False

                try:
                    traced_result = json.loads(content)
                except json.JSONDecodeError:
                    traced_result = content
                self._trace("Tool output", traced_result)
                await self._emit(
                    "tool_completed",
                    id=event_id,
                    name=name,
                    succeeded=succeeded,
                    result=traced_result,
                )

                tool_message = {"role": "tool", "tool_name": name, "content": content}
                if tool_call_id:
                    tool_message["tool_call_id"] = tool_call_id
                self.messages.append(tool_message)

        raise RuntimeError(f"Agent exceeded the {self.max_rounds}-round tool-call limit")
