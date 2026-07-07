"""Test script for akshare-jc-mcp.
Usage: python3.13 test_mcp.py [symbol] [features...]
Default: python3.13 test_mcp.py 000625 time_info realtime
"""

import json
import sys
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_ARGS = ["-m", "akshare_jc_mcp"]


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "000625"
    features = sys.argv[2:] if len(sys.argv) > 2 else ["time_info", "realtime"]

    params = StdioServerParameters(
        command="python3.13",
        args=SERVER_ARGS,
    )

    async with stdio_client(params) as (read, write):
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()

            # List tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"Registered tools: {tool_names}")

            # Call get_data
            print(f"\nCalling get_data(symbol={symbol!r}, features={features!r})...\n")
            result = await session.call_tool(
                "get_data",
                arguments={"symbol": symbol, "features": features},
            )

            data = json.loads(result.content[0].text)
            print(json.dumps(data, ensure_ascii=False, indent=2))

            # Summary
            print("\n--- Summary ---")
            for entry in data:
                status = "OK" if not entry["error"] else f"ERR: {entry['error_reason']}"
                print(f"  {entry['feature']}: {status}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
