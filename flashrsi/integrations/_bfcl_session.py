"""Public Base conversation protocol and private replay evidence."""

import ast
import copy
import json

from ._bfcl_native import _Session


def decoded_call(name, arguments):
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
        raise ValueError("Invalid function name")
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    if not isinstance(arguments, dict) or any(
        not isinstance(key, str) or not key.isidentifier() for key in arguments
    ):
        raise ValueError("Expected named JSON arguments")
    arguments = json.loads(json.dumps(arguments, allow_nan=False))
    call = (
        name
        + "("
        + ", ".join(f"{key}={value!r}" for key, value in arguments.items())
        + ")"
    )
    ast.parse(call, mode="eval")
    return call


class Conversation:
    """Host-owned state; never passed to the native Agent process."""

    def __init__(self, package, row, max_calls_per_turn=256):
        self.session = _Session(package, row)
        self.turns = len(row["question"])
        self.limit = max_calls_per_turn
        self.calls = 0
        self.total_calls = 0
        self.finished = False
        self.interrupted = None
        self.rejected = False
        self.current = self.session.begin_turn()

    def public(self):
        if self.interrupted:
            return {
                "event": "conversation_interrupted",
                "interrupted": self.interrupted,
            }
        if self.finished:
            return {"event": "conversation_complete"}
        return {
            "event": "user_turn",
            "messages": [
                {key: message[key] for key in ("role", "content")}
                for message in self.current["messages"]
            ],
            **self._tools(),
        }

    def _tools(self, name=None):
        tools = self.current["tools"] if not self.finished else []
        return {
            "tools": [
                {
                    key: copy.deepcopy(tool[key])
                    for key in ("name", "description", "parameters")
                }
                for tool in tools
                if name is None or tool["name"] == name
            ]
        }

    def respond(self, request):
        operation = request.get("operation")
        if operation == "current":
            return self.public()
        if operation == "tools":
            return self._tools(request.get("name"))
        if operation not in ("call", "finish_turn"):
            self.rejected = True
            raise PermissionError("Unavailable BFCL operation")
        if self.finished or self.interrupted:
            self.rejected = True
            raise ValueError("No active BFCL turn")
        if operation == "finish_turn":
            self.session.end_turn()
            self.turns -= 1
            self.calls = 0
            if self.turns:
                self.current = self.session.begin_turn()
            else:
                self.finished = True
            return self.public()
        batch = request.get("calls")
        if not isinstance(batch, list) or not batch:
            self.rejected = True
            raise ValueError("Nonempty calls required; use finish_turn otherwise")
        if self.calls + len(batch) > self.limit or self.total_calls + len(batch) > 2048:
            self.interrupted = "tool_rpc_limit"
            return {
                "event": "tool_results",
                "results": [],
                "interrupted": self.interrupted,
            }
        self.calls += len(batch)
        self.total_calls += len(batch)
        results = []
        for call in batch:
            try:
                decoded = decoded_call(call["name"], call["arguments"])
                observation = self.session.execute([decoded])
                results.append({"content": observation["tool_responses"][0]})
            except (ValueError, SyntaxError, TypeError, KeyError):
                self.rejected = True
                results.append({"content": "Tool call rejected", "isError": True})
        return {"event": "tool_results", "results": results}

    def evidence(self):
        return {
            "complete": self.finished,
            "protocol_valid": self.finished
            and not self.rejected
            and not self.interrupted,
            "interrupted": self.interrupted,
            "trace": self.session.trace()
            if self.finished
            else copy.deepcopy(self.session._calls),
        }

    def close(self):
        self.session.close()
