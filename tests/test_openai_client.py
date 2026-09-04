import json
import unittest

from crew_ops.openai_client import OpenAIClient, _response_tools


class OpenAIClientTests(unittest.TestCase):
    def test_converts_mcp_tool_schema_for_responses_api(self) -> None:
        converted = _response_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_crew",
                        "description": "Get crew",
                        "parameters": {
                            "type": "object",
                            "properties": {"crew_id": {"type": "string"}},
                            "required": ["crew_id"],
                        },
                    },
                }
            ]
        )
        self.assertEqual(converted[0]["name"], "get_crew")
        self.assertEqual(converted[0]["type"], "function")

    def test_converts_tool_result_to_function_call_output(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Get C-1042"},
            {"role": "assistant", "content": "", "tool_calls": []},
            {
                "role": "tool",
                "tool_name": "get_crew",
                "tool_call_id": "call-1",
                "content": json.dumps({"crew_id": "C-1042"}),
            },
        ]
        items = OpenAIClient._new_input(messages, 2)
        self.assertEqual(
            items,
            [
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": '{"crew_id": "C-1042"}',
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
