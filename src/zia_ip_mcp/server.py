from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .data import ZiaIpDataError, find_entries, load_entries


mcp = FastMCP("zscaler-zia-ip-list")
_entries_cache: Optional[list[Any]] = None


def _entries() -> list[Any]:
    global _entries_cache
    if _entries_cache is None:
        _entries_cache = load_entries()
    return _entries_cache


@mcp.tool()
def lookup_registered_zia_ips(query: str, limit: int = 10) -> dict[str, Any]:
    """Look up registered-user Zscaler ZIA IP CIDRs by location."""
    try:
        matches = find_entries(_entries(), query, limit)
    except ZiaIpDataError as exc:
        return {"query": query, "matches": [], "error": str(exc)}

    return {
        "query": query,
        "matches": [entry.to_dict() for entry in matches],
        "note": "Only registered-user IP/CIDR fields are returned. Non-registered-user fields are ignored.",
    }


@mcp.tool()
def list_zia_locations(search: str = "", limit: int = 50) -> dict[str, Any]:
    """List available Zscaler ZIA locations from the configured data source."""
    try:
        entries = _entries()
    except ZiaIpDataError as exc:
        return {"locations": [], "error": str(exc)}

    if search:
        entries = find_entries(entries, search, limit)
    else:
        entries = sorted(entries, key=lambda entry: entry.location.lower())[: max(1, limit)]

    return {
        "locations": [
            {"location": entry.location, "registered_ip_count": len(entry.registered_ips)}
            for entry in entries
        ]
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

