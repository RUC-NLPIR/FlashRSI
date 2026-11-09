"""Native MCP discovery and completed calls, without server config or secrets."""

import asyncio


async def evidence(client, messages):
    try:
        status = await asyncio.wait_for(client.get_mcp_status(), timeout=10)
        servers = [
            {
                "name": server["name"],
                "status": server["status"],
                "tools": [tool["name"] for tool in server.get("tools", [])],
            }
            for server in status["mcpServers"]
        ]
    except Exception as exc:
        # Observability must not turn an otherwise successful task into a failure.
        # A gate requiring MCP evidence will reject this explicit missing proof.
        return {"type": "MCPStatus", "error": str(exc) or type(exc).__name__}

    uses, completed = {}, set()
    for message in messages:
        if message.get("type") == "AssistantMessage":
            for block in message.get("content", []):
                if block.get("type") == "ToolUseBlock":
                    uses[block["id"]] = block["name"]
        if message.get("type") == "UserMessage":
            for block in message.get("content", []):
                if (
                    block.get("type") == "ToolResultBlock"
                    and not block.get("is_error")
                    and block.get("tool_use_id") in uses
                ):
                    completed.add(uses[block["tool_use_id"]])
    return {
        "type": "MCPStatus",
        "servers": servers,
        "successful_calls": sorted(
            name for name in completed if name.startswith("mcp__")
        ),
    }
