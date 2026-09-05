import unittest
from types import SimpleNamespace

from crew_ops.reengineering_agent import (
    LEGAL_COMPLIANCE_TOOLS,
    REENGINEERING_READ_TOOLS,
    ReengineeredCrewOpsAdvisor,
    classify_for_reengineering,
)


class FakeSession:
    def __init__(self) -> None:
        names = [
            "get_crew",
            "get_rules",
            "search_flights",
            "count_flights",
            "search_station_window",
            "assess_reserves_for_aircraft_duty",
            "search_crew_by_rolling_duty",
            "get_question",
        ]
        self.tools = [
            SimpleNamespace(
                name=name,
                description=name,
                inputSchema={"type": "object", "properties": {}},
            )
            for name in names
        ]
        self.list_calls = 0
        self.call_calls = []

    async def list_tools(self):
        self.list_calls += 1
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments):
        self.call_calls.append((name, arguments))
        return SimpleNamespace(
            isError=False,
            content=[SimpleNamespace(text='{"rules": [{"rule_id": "RULE-FDP-01"}]}')],
        )


class FixedClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0
        self.last_messages = []
        self.last_tools = []

    async def chat(self, messages, tools):
        self.calls += 1
        self.last_messages = [dict(message) for message in messages]
        self.last_tools = list(tools)
        return {"role": "assistant", "content": self.answer, "tool_calls": []}


class ReengineeringAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_accepts_only_yes_or_no(self) -> None:
        self.assertTrue(await classify_for_reengineering(FixedClient("YES"), "Recommend action"))
        self.assertFalse(await classify_for_reengineering(FixedClient("NO."), "List flights"))
        with self.assertRaises(RuntimeError):
            await classify_for_reengineering(FixedClient("MAYBE"), "Unclear")

    async def test_lookup_bypasses_reengineering_checker(self) -> None:
        session = FakeSession()
        solver = FixedClient("21 flights")
        classifier = FixedClient("NO")
        checker = FixedClient("unused")
        legal = FixedClient("unused")
        advisor = ReengineeredCrewOpsAdvisor(
            session,
            solver,
            lambda: classifier,
            lambda: checker,
            lambda: legal,
        )

        answer = await advisor.ask("How many flights operate on 16 Sep?")

        self.assertEqual(answer, "21 flights")
        self.assertEqual(classifier.calls, 1)
        self.assertEqual(checker.calls, 0)
        self.assertEqual(legal.calls, 0)
        self.assertEqual(session.list_calls, 1)
        self.assertEqual(session.call_calls, [])

    async def test_checker_sees_only_basic_read_tools(self) -> None:
        session = FakeSession()
        solver = FixedClient("draft solution")
        classifier = FixedClient("YES")
        checker = FixedClient("checked solution")
        legal = FixedClient("Legal status: PASS\n\nfinal legal solution")
        events = []

        async def collect(event):
            events.append(event)

        advisor = ReengineeredCrewOpsAdvisor(
            session,
            solver,
            lambda: classifier,
            lambda: checker,
            lambda: legal,
            event_handler=collect,
        )
        answer = await advisor.ask("Which recovery action should we take?")

        visible_names = {tool["function"]["name"] for tool in checker.last_tools}
        legal_visible_names = {tool["function"]["name"] for tool in legal.last_tools}
        self.assertEqual(answer, "Legal status: PASS\n\nfinal legal solution")
        self.assertEqual(visible_names, {"get_crew", "get_rules", "search_flights"})
        self.assertTrue(visible_names.issubset(REENGINEERING_READ_TOOLS))
        self.assertNotIn("count_flights", visible_names)
        self.assertNotIn("assess_reserves_for_aircraft_duty", visible_names)
        self.assertNotIn("search_crew_by_rolling_duty", visible_names)
        self.assertNotIn("get_question", visible_names)
        self.assertEqual(legal_visible_names, {"get_crew", "search_flights"})
        self.assertTrue(legal_visible_names.issubset(LEGAL_COMPLIANCE_TOOLS))
        self.assertNotIn("get_rules", legal_visible_names)
        self.assertNotIn("count_flights", legal_visible_names)
        self.assertNotIn("get_question", legal_visible_names)
        self.assertIn("draft solution", checker.last_messages[-1]["content"])
        self.assertEqual(session.call_calls, [("get_rules", {"rule_id": ""})])
        self.assertEqual(session.list_calls, 3)
        self.assertIn("checked solution", legal.last_messages[-1]["content"])
        self.assertIn("RULE-FDP-01", legal.last_messages[-1]["content"])
        self.assertIn("reengineering_started", [event["type"] for event in events])
        self.assertIn("legal_started", [event["type"] for event in events])
        self.assertIn("legal_completed", [event["type"] for event in events])
        self.assertTrue(events[-1]["reengineered"])
        self.assertTrue(events[-1]["legal_checked"])


if __name__ == "__main__":
    unittest.main()
