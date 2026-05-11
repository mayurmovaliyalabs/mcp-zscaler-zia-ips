from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def lookup(query: str, server_command: str, server_args: list[str], as_json: bool) -> int:
    params = StdioServerParameters(command=server_command, args=server_args, env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("lookup_registered_zia_ips", {"query": query})

    payload = _content_to_json(result.content)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


def _content_to_json(content: Any) -> dict[str, Any]:
    if not content:
        return {}
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return {"raw": str(first)}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _print_human(payload: dict[str, Any]) -> None:
    if payload.get("error"):
        print(f"Error: {payload['error']}", file=sys.stderr)
        return

    matches = payload.get("matches") or []
    if not matches:
        print(f"No registered-user ZIA IPs found for: {payload.get('query', '')}")
        return

    for match in matches:
        print(match["location"])
        for ip in match.get("registered_ips", []):
            print(f"  {ip}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the Zscaler ZIA IP MCP server.")
    parser.add_argument("query", help='Location query, for example "miami 3".')
    parser.add_argument("--json", action="store_true", help="Print the raw JSON tool response.")
    parser.add_argument(
        "--server-command",
        default=sys.executable,
        help="Command used to start the MCP server. Defaults to this Python interpreter.",
    )
    parser.add_argument(
        "--server-arg",
        action="append",
        dest="server_args",
        help="Argument passed to the MCP server command. Can be repeated.",
    )
    args = parser.parse_args()

    server_args = args.server_args or ["-m", "zia_ip_mcp.server"]
    raise SystemExit(asyncio.run(lookup(args.query, args.server_command, server_args, args.json)))


if __name__ == "__main__":
    main()

