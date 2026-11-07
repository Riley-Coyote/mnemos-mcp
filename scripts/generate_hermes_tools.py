#!/usr/bin/env python3
"""Write ``mnemos/integrations/hermes/tools.py``: the simple tools as plain schemas.

The Hermes provider offers the same tools as the MCP server, and can't count on
the MCP library inside Hermes' own Python, so it keeps a copy of what they say.
Run this after changing a tool; ``tests/test_hermes_same_tools.py`` fails until
the copy matches.
"""

from __future__ import annotations

import pprint
from pathlib import Path

from mnemos.simple_mcp import plain_tool_schemas

# Hermes wakes the agent itself, so it has no use for the tool that does.
LEFT_OUT = {"mnemos_context"}

HEAD = '''"""The simple tools as plain schemas, as the Hermes provider offers them.

Written by ``scripts/generate_hermes_tools.py`` from the MCP server's own tools,
and held to them by ``tests/test_hermes_same_tools.py``. Don't edit it by hand.
"""

from __future__ import annotations

from typing import Any

'''


def render() -> str:
    tools = [tool for tool in plain_tool_schemas() if tool["name"] not in LEFT_OUT]
    return f"{HEAD}TOOL_SCHEMAS: list[dict[str, Any]] = {pprint.pformat(tools, width=100, sort_dicts=False)}\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "mnemos/integrations/hermes/tools.py"
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target}")
