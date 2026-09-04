"""OpenAI Responses API adapter for the Crew Ops MCP agent."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError


class OpenAIClientError(RuntimeError):
    """Raised when the OpenAI API cannot complete an agent turn."""


def _response_tools(chat_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tools = []
    for tool in chat_tools:
        function = tool["function"]
        tools.append(
            {
                "type": "function",
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function["parameters"],
                "strict": False,
            }
        )
    return tools


class OpenAIClient:
    """Maintain Responses API state while presenting the agent's simple chat interface."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.6-terra",
        timeout_seconds: int = 180,
    ) -> None:
        if not api_key.strip():
            raise OpenAIClientError("OPENAI_API_KEY is not set in .env")
        self.client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self.model = model
        self.previous_response_id: Optional[str] = None
        self.seen_messages = 0

    @staticmethod
    def _new_input(messages: List[Dict[str, Any]], start: int) -> List[Dict[str, Any]]:
        items = []
        for message in messages[start:]:
            role = message["role"]
            if role == "user":
                items.append({"role": "user", "content": message.get("content", "")})
            elif role == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message["tool_call_id"],
                        "output": message.get("content", ""),
                    }
                )
            # Assistant messages are already retained by previous_response_id.
        return items

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(self._chat_sync, messages, tools)

    def _chat_sync(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        instructions = next(
            (message.get("content", "") for message in messages if message["role"] == "system"),
            "",
        )
        input_items = self._new_input(messages, self.seen_messages)
        request: Dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": _response_tools(tools),
            "parallel_tool_calls": True,
            "store": True,
        }
        if self.previous_response_id:
            request["previous_response_id"] = self.previous_response_id

        try:
            response = self.client.responses.create(**request)
        except AuthenticationError as exc:
            raise OpenAIClientError("OpenAI rejected the API key. Check OPENAI_API_KEY.") from exc
        except RateLimitError as exc:
            raise OpenAIClientError(f"OpenAI rate limit or quota reached: {exc.message}") from exc
        except APIConnectionError as exc:
            raise OpenAIClientError(f"Cannot reach the OpenAI API: {exc}") from exc
        except APIStatusError as exc:
            raise OpenAIClientError(f"OpenAI returned HTTP {exc.status_code}: {exc.message}") from exc

        self.previous_response_id = response.id
        self.seen_messages = len(messages)
        tool_calls = []
        for item in response.output:
            if item.type == "function_call":
                try:
                    arguments = json.loads(item.arguments)
                except json.JSONDecodeError:
                    arguments = item.arguments
                tool_calls.append(
                    {
                        "id": item.call_id,
                        "type": "function",
                        "function": {"name": item.name, "arguments": arguments},
                    }
                )

        return {
            "role": "assistant",
            "content": response.output_text or "",
            "tool_calls": tool_calls,
        }

