"""Fast, read-only re-engineering check for operational solutions."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from mcp import ClientSession

from crew_ops.agent import AgentEventHandler, ChatClient, CrewOpsAgent, tool_result_text


CLASSIFIER_PROMPT = """Decide whether this Crew Ops question asks for a proposed
action or solution. Return YES for recommendations, recovery actions, legality or
eligibility decisions, crew replacement/coverage, operational consequences, or steps
to solve a disruption. Return NO for simple lookup, list, count, identify, or explain
questions. Return exactly YES or NO and nothing else."""

# Raw, read-only dataset access only. Deliberately excludes deterministic assessment,
# aggregation, counting, overlap calculation, evaluation, and answer-key tools.
REENGINEERING_READ_TOOLS = {
    "get_crew",
    "search_crew",
    "get_flight",
    "search_flights",
    "get_pairing",
    "get_crew_roster",
    "get_reserves",
    "get_duty_clock",
    "get_certifications",
    "search_certifications",
    "get_risk_signal",
    "get_rules",
    "get_costs",
}

REENGINEERING_PROMPT = """You are the fast re-engineering checker for the fictional
dCortex Air dataset. You receive the user's question and a completed draft solution.
Your job is only to check the draft's important factual inputs against raw MCP records.

Use the minimum number of provided read-only tools, preferably in parallel, and stop
as soon as the key IDs, dates, times, qualifications, availability, rules, and costs
used by the draft are supported or contradicted. Make at most four tool calls unless a
missing raw record makes one additional call essential.

Do not perform a new optimization, exhaustive candidate search, deterministic
eligibility assessment, rolling-window computation, or disruption simulation. Do not
invent a different operational plan. Preserve the draft when raw records support it.
If a directly retrieved record contradicts a material claim, correct only that claim.

Return the checked user-facing answer directly and concisely. Do not mention agents,
drafts, checking, hidden reasoning, evaluation questions, or answer keys. All times are
UTC and dates in the operating week are in 2026."""

LEGAL_COMPLIANCE_TOOLS = {
    "get_crew",
    "search_crew",
    "get_flight",
    "search_flights",
    "get_pairing",
    "get_crew_roster",
    "get_reserves",
    "get_duty_clock",
    "get_certifications",
    "search_certifications",
}

LEGAL_COMPLIANCE_PROMPT = """You are the Legal Compliance Agent for the fictional
dCortex Air dataset. You run only for questions that propose an operational action.
You receive the original question, the checked proposed solution, and the complete
rules.json data loaded directly through MCP.

Determine whether the proposed action is legal on its operating date. Account for
every rule in the supplied rules data. For each rule, report PASS, FAIL, NOT APPLICABLE,
or UNKNOWN; never silently omit a rule. Use the available raw read tools to verify the
crew, flights, pairing, roster, reserves, duty clocks, and certifications needed to
apply those rules. Perform the date/time and hour arithmetic required by the rule
parameters. Do not use evaluation questions, scenarios, answer keys, or risk scores as
legal evidence.

If any applicable rule fails, the action is not legal. If required evidence is absent,
do not guess: report UNKNOWN and say what is missing. Start the response with exactly
one of `Legal status: PASS`, `Legal status: FAIL`, or `Legal status: UNKNOWN`. Then give
a concise rule-by-rule table with rule IDs and evidence, followed by the final corrected
operational answer. Do not mention other agents, drafts, or hidden reasoning. All times
are UTC, dates in the operating week are in 2026, and rule thresholds come only from
the supplied rules data."""

LLMFactory = Callable[[], ChatClient]


async def classify_for_reengineering(llm: ChatClient, question: str) -> bool:
    """Use a tool-free LLM call to decide whether the checker is needed."""
    response = await llm.chat(
        [
            {"role": "system", "content": CLASSIFIER_PROMPT},
            {"role": "user", "content": question},
        ],
        [],
    )
    decision = str(response.get("content", "")).strip().upper().rstrip(".! ")
    if decision == "YES":
        return True
    if decision == "NO":
        return False
    raise RuntimeError(f"Query classifier must return YES or NO, received: {decision!r}")


class ReengineeredCrewOpsAdvisor:
    """Run the solver and conditionally pass its solution through a raw-data checker."""

    def __init__(
        self,
        session: ClientSession,
        solver_llm: ChatClient,
        classifier_llm_factory: LLMFactory,
        checker_llm_factory: LLMFactory,
        legal_llm_factory: LLMFactory,
        *,
        verbose: bool = False,
        event_handler: Optional[AgentEventHandler] = None,
    ) -> None:
        self.session = session
        self.solver_llm = solver_llm
        self.classifier_llm_factory = classifier_llm_factory
        self.checker_llm_factory = checker_llm_factory
        self.legal_llm_factory = legal_llm_factory
        self.verbose = verbose
        self.event_handler = event_handler

    async def _emit(self, event_type: str, **data: Any) -> None:
        if self.event_handler is not None:
            await self.event_handler({"type": event_type, **data})

    def _tagged_handler(self, agent_name: str) -> AgentEventHandler:
        async def handle(event: Dict[str, Any]) -> None:
            if self.event_handler is None:
                return
            tagged = {**event, "agent": agent_name}
            if "id" in tagged:
                tagged["id"] = f"{agent_name}:{tagged['id']}"
            await self.event_handler(tagged)

        return handle

    async def ask(self, question: str) -> str:
        await self._emit("classification_started")
        needs_check = await classify_for_reengineering(
            self.classifier_llm_factory(),
            question,
        )
        await self._emit("classification_completed", needs_check=needs_check)

        solver = CrewOpsAgent(
            self.session,
            self.solver_llm,
            verbose=self.verbose,
            event_handler=self._tagged_handler("solver"),
        )
        await solver.initialize()
        draft = await solver.ask(question, emit_answer=False)
        await self._emit("solver_completed", content=draft)

        if not needs_check:
            await self._emit("answer", content=draft, reengineered=False)
            return draft

        await self._emit("reengineering_started")
        checker = CrewOpsAgent(
            self.session,
            self.checker_llm_factory(),
            max_rounds=4,
            verbose=self.verbose,
            event_handler=self._tagged_handler("reengineering"),
            system_prompt=REENGINEERING_PROMPT,
            allowed_tool_names=REENGINEERING_READ_TOOLS,
        )
        await checker.initialize()
        checked_answer = await checker.ask(
            "Original question:\n"
            f"{question}\n\n"
            "Completed solution to check against raw records:\n"
            f"{draft}",
            emit_answer=False,
        )
        await self._emit("reengineering_completed", content=checked_answer)

        await self._emit("legal_started")
        rules_call_id = "legal:all-rules"
        await self._emit(
            "tool_started",
            id=rules_call_id,
            name="get_rules",
            arguments={"rule_id": ""},
            agent="legal",
        )
        try:
            rules_result = await self.session.call_tool("get_rules", {"rule_id": ""})
            rules_content = tool_result_text(rules_result)
            rules_succeeded = not bool(rules_result.isError)
        except Exception as exc:
            rules_content = f'{{"error": {str(exc)!r}}}'
            rules_succeeded = False
        await self._emit(
            "tool_completed",
            id=rules_call_id,
            name="get_rules",
            succeeded=rules_succeeded,
            result=rules_content,
            agent="legal",
        )
        if not rules_succeeded:
            raise RuntimeError("Legal Compliance Agent could not load rules.json")

        legal_agent = CrewOpsAgent(
            self.session,
            self.legal_llm_factory(),
            max_rounds=8,
            verbose=self.verbose,
            event_handler=self._tagged_handler("legal"),
            system_prompt=LEGAL_COMPLIANCE_PROMPT,
            allowed_tool_names=LEGAL_COMPLIANCE_TOOLS,
        )
        await legal_agent.initialize()
        legal_answer = await legal_agent.ask(
            "Original question:\n"
            f"{question}\n\n"
            "Checked proposed solution:\n"
            f"{checked_answer}\n\n"
            "Complete rules.json MCP data:\n"
            f"{rules_content}",
            emit_answer=False,
        )
        await self._emit("legal_completed", content=legal_answer)
        await self._emit(
            "answer",
            content=legal_answer,
            reengineered=True,
            legal_checked=True,
        )
        return legal_answer
