"""MCP-specific acceptance of resource changes through public trajectory evidence."""

import json


def servers(snapshot):
    entry = snapshot.files.get(".mcp.json")
    if entry is None:
        return {}
    registry = json.loads(entry.content)
    if not isinstance(registry, dict) or not isinstance(
        registry.get("mcpServers"), dict
    ):
        raise ValueError(".mcp.json must contain an mcpServers mapping")
    values = registry["mcpServers"]
    if any(
        not isinstance(name, str) or not name.strip() or not isinstance(config, dict)
        for name, config in values.items()
    ):
        raise ValueError("MCP server registrations need names and config mappings")
    return values


def required(baseline, candidate, tool_files):
    changed = set(baseline.changed_paths(candidate))
    if ".mcp.json" not in changed and not changed.intersection(tool_files):
        return None
    if ".mcp.json" not in baseline.files and ".mcp.json" not in candidate.files:
        return None
    before, after = servers(baseline), servers(candidate)
    names = {name for name in after if before.get(name) != after[name]}
    # A server implementation can change while its registration stays identical.
    if changed.intersection(set(tool_files) - {".mcp.json"}):
        names.update(after)
    return {
        "required_servers": sorted(names),
        "removed_servers": sorted(before.keys() - after.keys()),
    }


def validate(requirements, trajectories):
    """Every run must discover the changed servers; calls may span the batch."""
    called = set()
    if not trajectories:
        raise ValueError("MCP validation requires execution evidence")
    for trajectory in trajectories:
        records = [m for m in trajectory.messages if m.get("type") == "MCPStatus"]
        if len(records) != 1 or records[0].get("error"):
            raise ValueError("Target did not provide usable MCPStatus evidence")
        record = records[0]
        active = {server["name"]: server for server in record["servers"]}
        for name in requirements["removed_servers"]:
            if name in active:
                raise ValueError(f"Removed MCP server still loaded: {name}")
        for name in requirements["required_servers"]:
            server = active.get(name)
            if server is None or server["status"] != "connected":
                raise ValueError(f"MCP server not connected: {name}")
            tools = server["tools"]
            if not tools:
                raise ValueError(f"MCP server exposes no tools: {name}")
            qualified = {
                tool if tool.startswith(f"mcp__{name}__") else f"mcp__{name}__{tool}"
                for tool in tools
            }
            if qualified.intersection(record["successful_calls"]):
                called.add(name)
    missing = set(requirements["required_servers"]) - called
    if missing:
        raise ValueError(
            "No successful MCP tool call for servers: " + ", ".join(sorted(missing))
        )
    return {"called_servers": sorted(called)}
