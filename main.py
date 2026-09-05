"""Interactive entry point for the local Crew Ops Advisor."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from crew_ops.openai_client import OpenAIClient, OpenAIClientError
from crew_ops.reengineering_agent import ReengineeredCrewOpsAdvisor


load_dotenv()
console = Console()


def print_answer(answer: str) -> None:
    console.print(
        Panel(
            Markdown(answer),
            title="[bold bright_cyan]Crew Ops Advisor[/bold bright_cyan]",
            title_align="left",
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask the Crew Ops dataset through OpenAI and MCP")
    parser.add_argument("question", nargs="*", help="One question; omit for interactive mode")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=os.getenv("CREW_OPS_VERBOSE", "").casefold() in {"1", "true", "yes"},
        help="Print MCP tool names, inputs, and complete outputs while processing",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "crew_ops.mcp_server"],
        env=os.environ.copy(),
    )
    api_key = os.getenv("OPENAI_API_KEY", "")
    classifier_model = os.getenv("OPENAI_CLASSIFIER_MODEL", "").strip() or "gpt-4o-mini"
    checker_model = os.getenv("OPENAI_REENGINEERING_MODEL", "").strip() or "gpt-4o-mini"
    legal_model = os.getenv("OPENAI_LEGAL_MODEL", "").strip() or args.model

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            async def ask_question(question: str) -> str:
                advisor = ReengineeredCrewOpsAdvisor(
                    session,
                    OpenAIClient(api_key=api_key, model=args.model),
                    lambda: OpenAIClient(api_key=api_key, model=classifier_model),
                    lambda: OpenAIClient(api_key=api_key, model=checker_model),
                    lambda: OpenAIClient(api_key=api_key, model=legal_model),
                    verbose=args.verbose,
                )
                return await advisor.ask(question)

            if args.question:
                try:
                    answer = await ask_question(" ".join(args.question))
                except OpenAIClientError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    return 1
                print_answer(answer)
                return 0

            print(f"Crew Ops Advisor (OpenAI: {args.model}). Type 'exit' to quit.")
            while True:
                try:
                    question = input("\nYou: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0
                if question.casefold() in {"exit", "quit"}:
                    return 0
                if not question:
                    continue
                try:
                    answer = await ask_question(question)
                except OpenAIClientError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    return 1
                print()
                print_answer(answer)


def run() -> None:
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except OpenAIClientError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    run()
