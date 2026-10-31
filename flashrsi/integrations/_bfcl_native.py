"""Native session/replay seam migrated from the frozen OOD adapter.

Official source: ShishirPatil/gorilla at
6ea57973c7a6097fd7c5915698c54c17c5b1b6c8. Only JSON-literal calls
reach native execution; no model SDK or historical experiment module is imported.
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import sys
import uuid
from pathlib import Path

CATEGORIES = ("multi_turn_base",)


def literal_constant(path, name):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError(f"Missing official constant {name}")


def _official(package):
    sys.path.insert(0, str(package))
    for name, module in list(sys.modules.items()):
        if name.startswith("bfcl_eval") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(package.resolve()):
                raise ValueError("Another BFCL installation is already imported")
    utils = importlib.import_module(
        "bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils"
    )
    checker = importlib.import_module(
        "bfcl_eval.eval_checker.multi_turn_eval.multi_turn_checker"
    )
    return utils, checker


def _compile_entry(package, row):
    """Reuse the verified official function loader without importing model SDKs.

    Compile only this pure data helper from utils.py, with its exact original
    body and explicit dependencies. Never execute the API generation handlers.
    """
    source = package / "bfcl_eval/utils.py"
    nodes = ast.parse(source.read_text(encoding="utf-8")).body
    function = next(
        n
        for n in nodes
        if isinstance(n, ast.FunctionDef)
        and n.name == "populate_test_cases_with_predefined_functions"
    )
    namespace = {
        "is_multi_turn": lambda value: value.rsplit("_", 1)[0] in CATEGORIES,
        "is_agentic": lambda _: False,
        "load_file": lambda p: [
            json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
        ],
        "MULTI_TURN_FUNC_DOC_PATH": package / "bfcl_eval/data/multi_turn_func_doc",
        "MULTI_TURN_FUNC_DOC_FILE_MAPPING": literal_constant(
            package / "bfcl_eval/constants/executable_backend_config.py",
            "MULTI_TURN_FUNC_DOC_FILE_MAPPING",
        ),
    }
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    return namespace[function.name]([copy.deepcopy(row)])[0]


def _validate_call(call, allowed):
    expression = ast.parse(call, mode="eval").body
    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id not in allowed
    ):
        raise ValueError("Call is not a currently available BFCL function")
    if any(keyword.arg is None for keyword in expression.keywords):
        raise ValueError("Expanded keyword arguments are not supported")
    for argument in [*expression.args, *(k.value for k in expression.keywords)]:
        ast.literal_eval(argument)


class _Session:
    """One independently reset official environment; never expose this object."""

    def __init__(self, package, row):
        self._package = package
        self._row = _compile_entry(package, row)
        self._utils, _ = _official(package)
        self._namespace = "offline_" + uuid.uuid4().hex
        self._turn = -1
        self._ended = True
        self._closed = False
        self._calls = []

    def begin_turn(self):
        if self._closed or not self._ended:
            raise ValueError("Previous turn must be ended and session open")
        if self._turn + 1 >= len(self._row["question"]):
            raise ValueError("No remaining user turn")
        self._turn += 1
        self._ended = False
        self._calls.append([])
        messages = copy.deepcopy(self._row["question"][self._turn])
        added = self._row.get("missed_function", {}).get(str(self._turn), [])
        if added:
            if messages:
                raise ValueError(
                    "Official function-release turn must have no user message"
                )
            self._row["function"].extend(added)
            prompt = literal_constant(
                self._package / "bfcl_eval/constants/default_prompts.py",
                "DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC",
            )
            messages = [{"role": "user", "content": prompt}]
        # Explicit allowlist; no whole-entry serialization, future messages,
        # reference calls, initial state, path, task ID or grading metadata.
        return {"messages": messages, "tools": copy.deepcopy(self._row["function"])}

    def execute(self, calls):
        if self._closed or self._ended or not calls:
            raise ValueError(
                "Tool execution requires an active turn and nonempty calls"
            )
        if not isinstance(calls, list) or not all(isinstance(c, str) for c in calls):
            raise ValueError("Expected decoded BFCL call strings")
        allowed = {tool["name"] for tool in self._row["function"]}
        for call in calls:
            _validate_call(call, allowed)
        results, _ = self._utils.execute_multi_turn_func_call(
            calls,
            self._row["initial_config"],
            self._row["involved_classes"],
            self._namespace,
            self._row["id"],
            long_context="long_context" in self._row["id"],
        )
        self._calls[-1].append(copy.deepcopy(calls))
        return {"tool_responses": results}

    def end_turn(self):
        if self._closed or self._ended:
            raise ValueError("No active user turn")
        self._ended = True

    def trace(self):
        if not self._ended or len(self._calls) != len(self._row["question"]):
            raise ValueError("Incomplete conversation")
        return copy.deepcopy(self._calls)

    def close(self):
        for key in list(vars(self._utils)):
            if key.startswith(self._namespace + "_") and key.endswith("_instance"):
                delattr(self._utils, key)
        self._closed = True


def score_conversation(package, row, reference, decoded_calls):
    """Controller only: official state/response AND irrelevance checks."""
    if not isinstance(decoded_calls, list) or len(decoded_calls) != len(
        row["question"]
    ):
        return {"success": False, "error_type": "incomplete_conversation"}
    utils, checker = _official(package)
    namespace = "score_" + uuid.uuid4().hex
    try:
        entry = _compile_entry(package, row)
        tools = {tool["name"] for tool in entry["function"]}
        for turn, steps in enumerate(decoded_calls):
            tools.update(
                t["name"] for t in entry.get("missed_function", {}).get(str(turn), [])
            )
            for calls in steps:
                for call in calls:
                    _validate_call(call, tools)
        state = checker.multi_turn_checker(
            copy.deepcopy(decoded_calls),
            reference,
            row,
            row["id"].rsplit("_", 1)[0],
            namespace,
        )
        relevance = checker.multi_turn_irrelevance_checker(decoded_calls, reference)
        return {
            "success": bool(state["valid"] and relevance["valid"]),
            "state_and_response_valid": state["valid"],
            "irrelevance_valid": relevance["valid"],
            "error_type": state.get("error_type") or relevance.get("error_type"),
        }
    finally:
        for key in list(vars(utils)):
            if key.startswith(namespace + "_") and key.endswith("_instance"):
                delattr(utils, key)
