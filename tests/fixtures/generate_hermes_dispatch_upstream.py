"""Full, local Hermes tool-dispatch differential probe (no model calls).

Reproduce from the FlashRSI checkout:
  uv pip install --target /tmp/hermes-v0225-oracle-deps ruamel.yaml psutil
  .venv/bin/python tests/fixtures/generate_hermes_dispatch_upstream.py \
    --upstream /tmp/hermes-agent-v0.22.5-source \
    --deps /tmp/hermes-v0225-oracle-deps

Upstream must be commit bf0203a794a07aac3ff764972ab9087baa4e4f4e.
Only boundary injection: isolated HERMES_HOME/config/cwd; original LocalEnvironment
shell transport is forced non-login so it does not load the host's shell rc files.
The upstream registry, registered handlers, guards, tracking, file operations,
search backend, lint, bash session scripts and result encoders run unmodified.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PIN = "bf0203a794a07aac3ff764972ab9087baa4e4f4e"
REPO = Path(__file__).resolve().parents[2]
FIXTURE_CASES = {
    "binary_text_write_guards",
    "single_file_search_and_guards",
    "terminal_exit_semantics",
    "v4a_mixed_operations",
    "v4a_move_update_overlay",
    "v4a_apply_syntax_failure",
    "complex_bom_crlf",
    "paged_stale_overwrite",
    "patch_errors_and_already_applied",
    "terminal_state_and_errors",
    "read_errors_and_repetition",
    "binary_read_dispatch_guards",
    "search_ignore_glob_semantics",
    "search_multiline_regex",
    "read_notebook_document",
    "stdlib_document_formats",
}


def call(tool, **args):
    return {"tool": tool, "args": args}


def scenario(name, files, steps):
    return {
        "name": name,
        "files": {
            name: content.hex()
            if isinstance(content, bytes)
            else content.encode().hex()
            for name, content in files.items()
        },
        "steps": steps,
    }


def stdlib_documents():
    def archive(entries):
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w") as bundle:
            for name, content in entries.items():
                bundle.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), content)
        return result.getvalue()

    database = sqlite3.connect(":memory:")
    database.execute("CREATE TABLE items(id INTEGER, name TEXT)")
    database.execute("INSERT INTO items VALUES(1, 'first')")
    sqlite = database.serialize()
    database.close()
    return {
        "document.docx": archive(
            {
                "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Heading</w:t><w:br/><w:t>Second</w:t></w:r></w:p></w:body></w:document>'
            }
        ),
        "sheet.xlsx": archive(
            {
                "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" r:id="r1"/></sheets></workbook>',
                "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
                "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="inlineStr"><is><t>Value</t></is></c><c r="C1"><v>42</v></c></row></sheetData></worksheet>',
            }
        ),
        "data.db": sqlite,
        "bad.docx": b"not a zip archive",
    }


SCENARIOS = [
    scenario(
        "binary_read_dispatch_guards",
        {
            "image.png": b"\x89PNG\r\n\x1a\n\x00image",
            "sample.bin": b"binary",
            "looks.png.txt": b"plain text\n",
        },
        [
            call("read_file", path="image.png"),
            call("read_file", path="sample.bin"),
            call("read_file", path="looks.png.txt"),
        ],
    ),
    scenario(
        "search_ignore_glob_semantics",
        {
            ".git/config": "",
            ".gitignore": "ignored.txt\n",
            "ignored.txt": "needle\n",
            "src/visible.txt": "visible needle\n",
            "visible.txt": "root needle\n",
            ".hidden.txt": "hiddenonly\n",
        },
        [
            call("search_files", pattern="needle", file_glob="src/*.txt"),
            call("search_files", pattern="needle", file_glob="ignored.txt"),
            call("search_files", pattern="hiddenonly"),
        ],
    ),
    scenario(
        "search_multiline_regex",
        {"one.txt": "alpha\nbeta\nlast\n"},
        [call("search_files", pattern="alpha\\nbeta", path="one.txt")],
    ),
    scenario(
        "read_notebook_document",
        {
            "note.ipynb": '{"cells":[{"cell_type":"markdown","source":["# Header\\n","text"]},{"cell_type":"code","source":["print(1)\\n"],"outputs":[{"output_type":"stream","text":["1\\n"]}]}]}'
        },
        [call("read_file", path="note.ipynb")],
    ),
    scenario(
        "stdlib_document_formats",
        stdlib_documents(),
        [
            call("read_file", path="document.docx", limit=1),
            call("read_file", path="document.docx"),
            call("read_file", path="sheet.xlsx"),
            call("read_file", path="data.db"),
            call("read_file", path="bad.docx"),
        ],
    ),
    scenario(
        "binary_text_write_guards",
        {"image.png": b"\x89PNG\r\n\x1a\n\x00original image bytes"},
        [
            call("write_file", path="image.png", content="not an image"),
            call("patch", path="image.png", old_string="old", new_string="new"),
            call(
                "patch",
                mode="patch",
                patch="*** Begin Patch\n*** Update File: image.png\n@@\n+not an image\n*** End Patch",
            ),
            call("write_file", path="new.docx", content="not a document"),
            call("write_file", path="db.sqlite-wal", content="not database pages"),
        ],
    ),
    scenario(
        "single_file_search_and_guards",
        {"one.txt": "head\nhit one\nmid\nhit two\ntail\n"},
        [
            call("search_files", pattern="hit", path=".", limit=1),
            call("search_files", pattern="hit", path=".", limit=1, offset=1),
            call("search_files", pattern="hit", path=".", output_mode="count"),
            call("search_files", pattern="hit", path=".", output_mode="files_only"),
            call("search_files", pattern="*.txt", path=".", target="files"),
            call("search_files", pattern="head", path="one.txt"),
            call("search_files", pattern="head", path="one.txt"),
            call("search_files", pattern="head", path="one.txt"),
            call("search_files", pattern="head", path="one.txt"),
        ],
    ),
    scenario(
        "terminal_exit_semantics",
        {"note.txt": "plain\n"},
        [
            call("terminal", command="grep absent note.txt"),
            call("terminal", command="printf '\\033[31mred\\033[0m'"),
            call("terminal", command="hermes_parity_command_does_not_exist"),
            call("terminal", command="true", timeout=181),
            call("terminal", command=None),
        ],
    ),
    scenario(
        "v4a_mixed_operations",
        {
            "a.txt": "\ufeffheader\r\nold value\r\nfooter\r\n",
            "move.txt": "moved payload\n",
            "remove.txt": "deleted payload\n",
        },
        [
            call("read_file", path="a.txt"),
            call(
                "patch",
                mode="patch",
                patch="*** Begin Patch\n*** Update File: a.txt\n@@\n-old value\n+new value\n*** Add File: added.txt\n+brand new\n*** Move File: move.txt -> moved.txt\n*** Delete File: remove.txt\n*** End Patch",
            ),
            call(
                "write_file",
                path="a.txt",
                content="header\nwhole view retained\nfooter\n",
            ),
            call(
                "write_file",
                path="added.txt",
                content="newly authored baseline retained\n",
            ),
            call("read_file", path="moved.txt"),
            call(
                "patch",
                mode="patch",
                patch="*** Begin Patch\n*** Update File: a.txt\n@@\n-header\n+CHANGED_HEADER\n*** Add File: added.txt\n+must refuse occupied Add\n*** End Patch",
            ),
        ],
    ),
    scenario(
        "v4a_move_update_overlay",
        {"source.txt": "anchor\nbody old\nend\n"},
        [
            call(
                "patch",
                mode="patch",
                patch="*** Begin Patch\n*** Move File: source.txt -> dest.txt\n*** Update File: dest.txt\n@@\n-body old\n+body new\n@@ anchor @@\n+inserted after anchor\n*** End Patch",
            ),
            call("read_file", path="dest.txt"),
            call(
                "patch",
                mode="patch",
                patch="*** Begin Patch\n*** Add File: ../escape.txt\n+rejected\n*** End Patch",
            ),
        ],
    ),
    scenario(
        "v4a_apply_syntax_failure",
        {"a.txt": "original\n", "data.json": '{"good": true}\n'},
        [
            call(
                "patch",
                mode="patch",
                patch='*** Begin Patch\n*** Update File: a.txt\n@@\n-original\n+changed before syntax gate\n*** Update File: data.json\n@@\n-{"good": true}\n+{"broken":\n*** End Patch',
            ),
        ],
    ),
    scenario(
        "complex_bom_crlf",
        {"note.txt": "\ufeffheader\r\nif ready:\r\n    old('x')   \r\nfooter\r\n"},
        [
            call("read_file", path="note.txt"),
            call(
                "patch",
                path="note.txt",
                old_string="if ready:\n  old('x')",
                new_string="if ready:\n  newer('x')",
            ),
            call("read_file", path="note.txt"),
            call(
                "write_file",
                path="note.txt",
                content="header\nif ready:\n    final('x')\nfooter\n",
            ),
            call("read_file", path="note.txt"),
        ],
    ),
    scenario(
        "paged_stale_overwrite",
        {"pages.txt": "one\ntwo\nthree\nfour\n"},
        [
            call("write_file", path="pages.txt", content="blind overwrite\n"),
            call("read_file", path="pages.txt", offset=1, limit=2),
            call("read_file", path="pages.txt", offset=3, limit=2),
            call("write_file", path="pages.txt", content="authored\n"),
            {"external_write": {"path": "pages.txt", "content": "concurrent change\n"}},
            call("write_file", path="pages.txt", content="lost external edit\n"),
            call("read_file", path="pages.txt"),
            call("write_file", path="pages.txt", content="merged current\n"),
        ],
    ),
    scenario(
        "patch_errors_and_already_applied",
        {"edit.txt": "same\nsame\nunique old value\n"},
        [
            call(
                "patch", path="edit.txt", old_string="same", new_string="SAME_CHANGED"
            ),
            call(
                "patch",
                path="edit.txt",
                old_string="missing unrelated xyz",
                new_string="new absent xyz",
            ),
            call(
                "patch",
                path="edit.txt",
                old_string="unique old value",
                new_string="unique new value",
            ),
            call(
                "patch",
                path="edit.txt",
                old_string="unique old value",
                new_string="unique new value",
            ),
            call(
                "patch",
                path="edit.txt",
                old_string="same",
                new_string="SAME_CHANGED",
                replace_all=True,
            ),
            call("read_file", path="edit.txt"),
        ],
    ),
    scenario(
        "structured_validation",
        {},
        [
            call("write_file", path="data.json", content='{"ok": true}\n'),
            call("write_file", path="data.json", content='{"broken":'),
            call("write_file", path="nan.json", content='{"value": NaN}'),
            call("write_file", path="good.toml", content='name = "value"\n'),
            call("write_file", path="broken.toml", content='items = ["missing"'),
            call("write_file", path="broken.py", content="def unfinished(\n"),
            call("write_file", path="numbered.txt", content="1|source\n2|display\n"),
        ],
    ),
    scenario(
        "terminal_state_and_errors",
        {"sub/note.txt": "inside subdir\n"},
        [
            call(
                "terminal",
                command="export HERMES_PARITY_VALUE='a b'; cd sub; printf '%s' ${HERMES_PARITY_VALUE// /_}",
            ),
            call("read_file", path="note.txt"),
            call("terminal", command="printf '%s\n' \"$HERMES_PARITY_VALUE\"; pwd"),
            call("terminal", command="pwd", workdir="<WORKDIR>"),
            call("terminal", command="pwd"),
            call("terminal", command="printf failure; false"),
            call("terminal", command=""),
            call("terminal", code="print('wrong argument')"),
            call("terminal", command="true", workdir="relative"),
        ],
    ),
    scenario(
        "terminal_timeout",
        {},
        [
            call(
                "terminal",
                command="printf before; sleep 3; printf after > delayed-write",
                timeout=1,
            ),
            call("terminal", command="printf recovered"),
        ],
    ),
    scenario(
        "content_search",
        {
            "a.txt": "before\nhit one\nafter\nhit two\n",
            "nested/b.txt": "hit nested\n",
            "skip.py": "hit filtered\n",
        },
        [
            call("search_files", pattern="hit", path=".", file_glob="*.txt", limit=2),
            call(
                "search_files",
                pattern="hit",
                path=".",
                file_glob="*.txt",
                limit=2,
                offset=2,
            ),
            call("search_files", pattern="hit", path=".", output_mode="files_only"),
            call("search_files", pattern="hit", path=".", output_mode="count"),
            call("search_files", pattern="hit one", path="a.txt", context=1),
            call("search_files", pattern="[", path="."),
        ],
    ),
    scenario(
        "filename_search",
        {"a.txt": "one\n", "nested/b.txt": "two\n", "other.py": "three\n"},
        [
            call("search_files", pattern="*.txt", path=".", target="files"),
            call("search_files", pattern="*.txt", path=".", target="files", limit=1),
            call(
                "search_files",
                pattern="*.txt",
                path=".",
                target="files",
                limit=1,
                offset=1,
            ),
        ],
    ),
    scenario(
        "todo_state_and_rejected_write",
        {},
        [
            call("todo_list"),
            call(
                "todo_list",
                todos=[
                    {"id": "1", "content": "parent", "status": "completed"},
                    {
                        "id": "2",
                        "content": "child",
                        "parent": "1",
                        "status": "in_progress",
                    },
                ],
            ),
            call(
                "todo_list",
                todos=[
                    {"id": "2", "status": "completed"},
                    {"id": "3", "content": "next step", "status": "pending"},
                ],
                merge=True,
            ),
            call("todo_list", todos=[{"id": "bad", "content": ""}]),
            call("todo_list"),
        ],
    ),
    scenario(
        "read_errors_and_repetition",
        {"note.txt": "kept\n", "sub/child.txt": "child\n"},
        [
            call("read_file", path="missing.txt"),
            call("read_file", path="sub"),
            call("read_file", path="note.txt"),
            call("read_file", path="note.txt"),
            call("read_file", path="note.txt"),
            call("read_file", path="note.txt"),
        ],
    ),
    scenario(
        "large_read_budget_continuation",
        {"large.txt": ("a" * 100 + "\n") * 1500},
        [
            call("read_file", path="large.txt"),
            call("read_file", path="large.txt", offset="<PREVIOUS_NEXT_OFFSET>"),
            call(
                "write_file", path="large.txt", content="complete view then replace\n"
            ),
        ],
    ),
]


def file_bytes(root):
    return {
        str(path.relative_to(root)): path.read_bytes().hex()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def normalize(value, root):
    if isinstance(value, str):
        return value.replace(str(root), "<WORKDIR>")
    if isinstance(value, list):
        return [normalize(item, root) for item in value]
    if isinstance(value, dict):
        return {
            normalize(key, root): normalize(item, root) for key, item in value.items()
        }
    return value


def worker(args):
    out = Path(args.output).resolve()
    work = out / "tools-work" / args.worker
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    profile = out / "tools-profiles" / args.worker
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "config.yaml").write_text(
        "terminal:\n  auto_source_bashrc: false\n  shell_init_files: []\n"
    )
    os.environ.update(
        HERMES_HOME=str(profile),
        TERMINAL_ENV="local",
        TERMINAL_CWD=str(work),
        HERMES_NATIVE_FILE_READ="1",
    )
    for name in ("BASH_ENV", "ENV"):
        os.environ.pop(name, None)
    sys.path.insert(0, str(Path(args.deps).resolve()))
    logging.basicConfig(level=logging.CRITICAL)
    imported = {}
    if args.worker == "upstream":
        upstream = Path(args.upstream).resolve()
        sys.path.insert(0, str(upstream))
        import model_tools
        import tools.file_tools as original_files
        import tools.terminal_tool as original_terminal
        import tools.todo_tool as original_todo
        from tools.environments.local import LocalEnvironment
        from tools.registry import registry

        original_run = LocalEnvironment._run_bash

        def nonlogin_transport(self, command, **kwargs):
            kwargs["login"] = False
            return original_run(self, command, **kwargs)

        LocalEnvironment._run_bash = nonlogin_transport
        for name, module in [
            ("model_tools", model_tools),
            ("file_tools", original_files),
            ("terminal_tool", original_terminal),
            ("todo_tool", original_todo),
        ]:
            path = Path(module.__file__)
            imported[name] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    else:
        sys.path.insert(0, str(REPO))
        from flashrsi.agents.hermes.runtime.hermes_native.tools import HermesTools
    cases = []
    for case in SCENARIOS:
        root = (work / case["name"]).resolve()
        root.mkdir()
        for name, content in case["files"].items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes.fromhex(content))
        task = "tool-parity-" + case["name"]
        if args.worker == "upstream":
            original_terminal.register_task_env_overrides(
                task, {"cwd": str(root), "env_type": "local"}
            )
            store = original_todo.TodoStore()

            def execute(name, parameters):
                if name == "todo_list":
                    return registry.dispatch(
                        name, parameters, task_id=task, store=store
                    )
                return model_tools.handle_function_call(name, parameters, task_id=task)
        else:
            native = HermesTools(root, REPO / "flashrsi/agents/hermes")
            execute = native.execute
        steps = []
        previous = {}
        try:
            for index, step in enumerate(case["steps"]):
                if "external_write" in step:
                    mutation = step["external_write"]
                    (root / mutation["path"]).write_text(mutation["content"])
                    steps.append(
                        {
                            "index": index,
                            "external_write": mutation,
                            "file_hex": file_bytes(root),
                        }
                    )
                    continue
                parameters = json.loads(json.dumps(step["args"]))
                for key, value in list(parameters.items()):
                    if value == "<WORKDIR>":
                        parameters[key] = str(root)
                    elif value == "<PREVIOUS_NEXT_OFFSET>":
                        parameters[key] = previous["next_offset"]
                started = time.monotonic()
                result = execute(step["tool"], parameters)
                elapsed = time.monotonic() - started
                try:
                    parsed = json.loads(result) if isinstance(result, str) else result
                except (ValueError, TypeError):
                    parsed = {"_unparsed": result}
                previous = parsed
                steps.append(
                    {
                        "index": index,
                        "tool": step["tool"],
                        "args": normalize(parameters, root),
                        "result": normalize(parsed, root),
                        "raw_result": result,
                        "elapsed_seconds": elapsed,
                        "file_hex": file_bytes(root),
                    }
                )
        finally:
            if args.worker == "upstream":
                key = original_terminal._resolve_container_task_id(task)
                env = original_terminal._active_environments.pop(key, None)
                if env is not None:
                    env.cleanup()
                original_terminal.clear_task_env_overrides(task)
            else:
                native.close()
        cases.append(
            {"name": case["name"], "steps": steps, "final_file_hex": file_bytes(root)}
        )
    result = {
        "implementation": args.worker,
        "upstream_commit": PIN,
        "actual_imported_modules": imported,
        "cases": cases,
    }
    target = out / f"tools-{args.worker}.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(str(target), flush=True)


def changes(left, right, path=""):
    if type(left) is not type(right):
        return [path or "$"]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(changes(left[key], right[key], child))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [path + ".length"]
        return [
            leaf
            for index, (a, b) in enumerate(zip(left, right))
            for leaf in changes(a, b, f"{path}[{index}]")
        ]
    return [] if left == right else [path or "$"]


def save_fixture(original, destination):
    """Keep actual dispatch results, arguments and every resulting file byte."""
    initial = {case["name"]: case["files"] for case in SCENARIOS}
    cases = []
    for case in original["cases"]:
        if case["name"] not in FIXTURE_CASES:
            continue
        steps = []
        for step in case["steps"]:
            steps.append(
                {
                    key: value
                    for key, value in step.items()
                    if key not in {"elapsed_seconds", "raw_result"}
                }
            )
        cases.append(
            {
                "name": case["name"],
                "initial_file_hex": initial[case["name"]],
                "steps": steps,
            }
        )
    evidence = {
        "upstream_repository": "https://github.com/NousResearch/hermes-agent",
        "upstream_commit": PIN,
        "generation": "Actual model_tools.handle_function_call with original registry, local backend, handlers, file guards and read tracking; no FlashRSI native code generates the expected outputs.",
        "boundary_injection": "Isolated HERMES_HOME/cwd, auto_source_bashrc=false and LocalEnvironment._run_bash(login=False). Only absolute workdirs are normalized to <WORKDIR>.",
        "cases": cases,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


def main(args):
    upstream = Path(args.upstream).resolve()
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=upstream, text=True
    ).strip()
    if actual != PIN:
        raise SystemExit(f"Upstream commit mismatch: {actual}")
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for implementation in ("upstream", "native"):
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            implementation,
            "--upstream",
            str(upstream),
            "--deps",
            str(Path(args.deps).resolve()),
            "--output",
            str(out),
        ]
        subprocess.run(command, cwd=REPO, check=True)
    original = json.loads((out / "tools-upstream.json").read_text())
    save_fixture(original, Path(args.fixture_output))
    native = json.loads((out / "tools-native.json").read_text())
    rows = []
    for left, right in zip(original["cases"], native["cases"]):
        step_rows = []
        for a, b in zip(left["steps"], right["steps"]):
            if "tool" not in a:
                continue
            step_rows.append(
                {
                    "index": a["index"],
                    "tool": a["tool"],
                    "structured_result_equal": a["result"] == b["result"],
                    "files_equal": a["file_hex"] == b["file_hex"],
                    "different_result_fields": changes(a["result"], b["result"]),
                }
            )
        rows.append(
            {
                "name": left["name"],
                "tool_calls": len(step_rows),
                "exact_result_matches": sum(
                    step["structured_result_equal"] for step in step_rows
                ),
                "all_step_file_bytes_equal": all(
                    step["files_equal"] for step in step_rows
                ),
                "final_file_bytes_equal": left["final_file_hex"]
                == right["final_file_hex"],
                "steps": step_rows,
            }
        )
    summary = {
        "upstream_repository": "https://github.com/NousResearch/hermes-agent",
        "upstream_commit": actual,
        "upstream_dispatch": "Actual model_tools.handle_function_call -> registry.dispatch -> registered handlers -> original file_tools/terminal_tool and LocalEnvironment; todo uses actual registry handler and original per-session TodoStore, as it is agent-loop-owned upstream.",
        "boundary_injection": [
            "HERMES_HOME points to an isolated run profile; auto_source_bashrc=false",
            "Actual LocalEnvironment._run_bash receives login=False to omit host shell rc startup",
            "Task overrides select the original local backend and separate controlled cwd per scenario",
        ],
        "normalization": "Only each case absolute workdir replaced with <WORKDIR> in structured results/arguments. Raw results retained. No result fields removed; timings recorded separately.",
        "oracle_dependencies": {
            "target_directory": str(Path(args.deps).resolve()),
            "requirements": ["ruamel.yaml==0.19.1", "psutil==7.2.2"],
        },
        "scenario_count": len(rows),
        "tool_call_count": sum(row["tool_calls"] for row in rows),
        "exact_structured_result_matches": sum(
            row["exact_result_matches"] for row in rows
        ),
        "all_step_file_bytes_equal": all(
            row["all_step_file_bytes_equal"] for row in rows
        ),
        "all_final_file_bytes_equal": all(
            row["final_file_bytes_equal"] for row in rows
        ),
        "cases": rows,
    }
    (out / "tools-comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "cases"}, indent=2
        )
    )
    for row in rows:
        print(
            f"{row['name']}: {row['exact_result_matches']}/{row['tool_calls']} result matches; file bytes {'MATCH' if row['all_step_file_bytes_equal'] else 'DIFFER'}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--deps", required=True)
    parser.add_argument("--output", default=str(REPO / "runs/hermes-parity-20261031"))
    parser.add_argument(
        "--fixture-output",
        default=str(Path(__file__).with_name("hermes_dispatch_upstream.json")),
    )
    parser.add_argument("--worker", choices=["upstream", "native"])
    parsed = parser.parse_args()
    worker(parsed) if parsed.worker else main(parsed)
