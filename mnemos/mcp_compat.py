"""Where Mnemos meets the MCP SDK's server API, on mcp 1.x and on 2.x.

mcp 2.0 renamed FastMCP to MCPServer and moved it to ``mcp.server.mcpserver``;
the old import raises ``ModuleNotFoundError`` on 2.x. A server's version is a
constructor argument there, where 1.x took it on its private low-level server,
and there is no ``get_context()``: a tool that wants the request asks for it
with a ``Context`` parameter, which both versions fill in and leave out of the
tool's input schema. The handshake's client name is ``client_info`` on 2.x and
``clientInfo`` on 1.x.

Hermes pins mcp 2 in its own environment, which is where its plugin catalog
installs Mnemos; Claude Code, Codex and the rest start ``mnemos serve`` with
whatever mcp the install resolved. Everything else in Mnemos goes through
here, so neither version is a second-class door.
"""

from __future__ import annotations

from typing import Any

try:  # mcp 2.x
    from mcp.server.mcpserver import Context, MCPServer as Server

    MCP_MAJOR = 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP as Server

    MCP_MAJOR = 1

__all__ = ["Context", "MCP_MAJOR", "Server", "client_name", "lowlevel_server", "make_server", "wire"]


def make_server(name: str, *, instructions: str, version: str) -> Server:
    """A server that tells clients its name, instructions and version."""

    if MCP_MAJOR >= 2:
        return Server(name, instructions=instructions, version=version)
    server = Server(name, instructions=instructions)
    server._mcp_server.version = version
    return server


def lowlevel_server(server: Server) -> Any:
    """The SDK's low-level server under a high-level one."""

    return server._lowlevel_server if MCP_MAJOR >= 2 else server._mcp_server


def wire(model: Any) -> dict[str, Any]:
    """An SDK model (a tool, a result) as it goes over the wire, keyed
    ``inputSchema``, ``isError``, ``structuredContent``. 1.x names its
    attributes that way and 2.x in snake_case, but both send these."""

    return model.model_dump(by_alias=True)


def client_name(ctx: Context | None) -> str:
    """The name the MCP client gave in its handshake, or "" when there's no
    request (a direct call) or it can't be read. Never raises."""

    try:
        params = ctx.session.client_params
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        return str(getattr(info, "name", "") or "").strip()
    except Exception:
        return ""
