import os
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_lists_and_calls_tools(self) -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "crew_ops.mcp_server"],
            env=os.environ.copy(),
        )
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("get_crew", names)
                self.assertIn("get_pairing", names)
                self.assertIn("get_rules", names)
                self.assertIn("assess_reserves_for_aircraft_duty", names)
                self.assertIn("count_flights", names)
                self.assertIn("search_crew_by_rolling_duty", names)
                self.assertIn("search_station_window", names)
                self.assertIn("search_certifications", names)
                self.assertNotIn("get_held_out_scenario", names)

                result = await session.call_tool("get_crew", {"crew_id": "C-1042"})
                self.assertFalse(result.isError)
                self.assertEqual(result.structuredContent["result"]["crew_id"], "C-1042")


if __name__ == "__main__":
    unittest.main()
