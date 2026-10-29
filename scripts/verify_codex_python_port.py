#!/usr/bin/env python3
"""Verify pinned provenance and copied resources, not semantic equivalence.

Python sources are a handwritten semantic port. Their upstream mapping is
checked for completeness; byte equality applies only to copied assets.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import tomllib
import urllib.request
from pathlib import Path

REPOSITORY = "https://github.com/openai/codex"
VERSION = "0.147.0"
TAG = "rust-v0.147.0"
COMMIT = "be6e8eac029b183056b7e4402879f15d2c85f61b"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE = ROOT / "flashrsi/agents/codex/python_core"
METADATA = {
    "assets/PROVENANCE.json",
    "context_assets/UPSTREAM.json",
    "resource_assets/upstream.json",
}
PINNED_DEPENDENCIES = {
    "bm25": (
        "2.3.2",
        "1cbd8ffdfb7b4c2ff038726178a780a94f90525ed0ad264c0afaa75dd8c18a64",
    ),
    "deunicode": (
        "1.6.2",
        "abd57806937c9cc163efc8ea3910e00a62e2aeb0b8119f1793a978088f8f6b04",
    ),
    "iana-time-zone": (
        "0.1.65",
        "e31bc9ad994ba00e440a8aa5c9ef0ec67d5cb5e5cb0cc7f8b744a35b389cc470",
    ),
    "rust-stemmers": (
        "1.2.0",
        "e46a2036019fdb888131db7a4c847a1063a7493f971ed94ea82c67eada63ca54",
    ),
    "stop-words": (
        "0.9.0",
        "645a3d441ccf4bf47f2e4b7681461986681a6eeea9937d4c3bc9febd61d17c71",
    ),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def crate_archive(name, version, checksum, offline):
    filename = f"{name}-{version}.crate"
    cache = ROOT / ".cache/codex-python-provenance" / filename
    candidates = [cache]
    registry_roots = [
        ROOT / ".cache/codex-build/toolchain/cargo/registry/cache",
        Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")) / "registry/cache",
    ]
    for root in registry_roots:
        candidates.extend(root.glob("*/" + filename))
    path = next((path for path in candidates if path.is_file()), None)
    if path is None:
        require(
            not offline,
            f"missing pinned crate archive {filename}; run once without --offline",
        )
        url = f"https://static.crates.io/crates/{name}/{filename}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        require(len(data) <= 8 * 1024 * 1024, f"oversized crate archive: {filename}")
        require(sha256(data) == checksum, f"crate checksum mismatch: {filename}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    else:
        data = path.read_bytes()
    require(sha256(data) == checksum, f"crate checksum mismatch: {filename}")
    return data


def raw_strings(source):
    return re.findall(r'r#+"([\s\S]*?)"#+', source)


def rust_string(literal):
    return json.loads(literal)


def derive(recipe, sources):
    source = sources[0].decode()
    if recipe == "posix_shell_snapshot_scripts":
        excluded = re.search(
            r"const EXCLUDED_EXPORT_VARS: &\[&str\] = &\[([^\]]+)\];", source
        )
        require(excluded is not None, "missing upstream excluded snapshot exports")
        names = [rust_string(value) for value in re.findall(r'"[^"\\]*"', excluded[1])]
        result = {}
        for shell in ("bash", "zsh", "sh"):
            function = re.search(
                r"fn "
                + shell
                + r'_snapshot_script\(\) -> String \{[\s\S]*?let script = r##"([\s\S]*?)"##;',
                source,
            )
            require(function is not None, f"missing upstream {shell} snapshot script")
            result[shell] = function[1].replace("EXCLUDED_EXPORTS", "|".join(names))
        return result
    if recipe.startswith("rust_raw_constant:"):
        name = recipe.split(":", 1)[1]
        match = re.search(
            r"const " + re.escape(name) + r': &str = r#"([\s\S]*?)"#;', source
        )
        require(match is not None, f"missing upstream constant: {name}")
        return match[1]
    if recipe.startswith("rust_json_function:"):
        name = recipe.split(":", 1)[1]
        raw = (
            source.split("fn " + name + "()", 1)[1]
            .split("json!(", 1)[1]
            .split(")\n}", 1)[0]
        )
        return json.loads(raw)
    if recipe == "subagents_v2_constants":
        config, mode = (value.decode() for value in sources[1:])
        section = source.split("fn spawn_agent_tool_description_v2(", 1)[1].split(
            "fn spawn_agent_models_description(", 1
        )[0]
        values = {"spawn_description": raw_strings(section)[0]}
        for key in (
            "ROOT_AGENT_USAGE_HINT_TEXT",
            "SUBAGENT_USAGE_HINT_TEXT",
            "SHARED_USAGE_HINT_TEXT",
        ):
            values[key.lower()] = re.search(
                "const DEFAULT_MULTI_AGENT_V2_" + key + r': &str = r#"([\s\S]*?)"#;',
                config,
            )[1]
        for key in ("MODEL_OVERRIDE_USAGE_HINT_TEXT", "WAIT_AGENT_USAGE_HINT_TEXT"):
            values[key.lower()] = rust_string(
                re.search(
                    "const DEFAULT_MULTI_AGENT_V2_"
                    + key
                    + r': &str =\s*("(?:\\.|[^"\\])*");',
                    config,
                )[1]
            )
        for key in (
            "EXPLICIT_REQUEST_ONLY_MULTI_AGENT_MODE_TEXT",
            "PROACTIVE_MULTI_AGENT_MODE_TEXT",
        ):
            values[key.lower()] = rust_string(
                re.search("const " + key + r': &str = ("(?:\\.|[^"\\])*");', mode)[1]
            )
        return values
    if recipe == "collaboration_output_schemas":

        def blocks(name):
            section = source.split("fn " + name + "(", 1)[1].split("\nfn ", 1)[0]
            return re.findall(r"json!\((\{.*?\n\s*\})\)", section, re.S)

        status = json.loads(blocks("agent_status_output_schema")[0])
        values = {"agent_status": status}
        for key, name in {
            "spawn_agent_v1": "spawn_agent_output_schema_v1",
            "send_input": "send_input_output_schema",
            "list_agents": "list_agents_output_schema",
            "resume_agent": "resume_agent_output_schema",
            "wait_agent_v1": "wait_output_schema_v1",
            "wait_agent_v2": "wait_output_schema_v2",
        }.items():
            values[key] = json.loads(
                blocks(name)[0].replace(
                    "agent_status_output_schema()", json.dumps(status)
                )
            )
        for key, raw in zip(
            ("spawn_agent_v2_hidden", "spawn_agent_v2"),
            blocks("spawn_agent_output_schema_v2"),
            strict=True,
        ):
            values[key] = json.loads(raw)
        for key, description in (
            ("close_agent", "The agent status observed before shutdown was requested."),
            (
                "interrupt_agent",
                "The agent status observed before the interrupt request was handled.",
            ),
        ):
            raw = blocks("agent_previous_status_output_schema")[0]
            values[key] = json.loads(
                raw.replace("agent_status_output_schema()", json.dumps(status)).replace(
                    "previous_status_description", json.dumps(description)
                )
            )
        return values
    if recipe == "skill_catalog_constants":
        values = {}
        pattern = r'const (SKILLS_\w+): &str = (r###"[\s\S]*?"###|"(?:[^"\\]|\\.)*");'
        for name, literal in re.findall(pattern, source):
            values[name] = (
                literal[5:-4] if literal.startswith("r###") else rust_string(literal)
            )
        require(len(values) == 4, "expected four upstream skill catalog constants")
        return values
    if recipe == "plugin_instructions":
        literals = re.findall(r'"((?:[^"\\]|\\.)*)"\.to_string\(\)', source)
        lines = [rust_string('"' + value + '"') for value in literals]
        protocol = sources[1].decode()
        markers = dict(
            re.findall(
                r'const (PLUGINS_INSTRUCTIONS_\w+_TAG): &str = "([^"]+)";', protocol
            )
        )
        return (
            markers["PLUGINS_INSTRUCTIONS_OPEN_TAG"]
            + "\n"
            + "\n".join([*lines, raw_strings(source)[0]])
            + "\n"
            + markers["PLUGINS_INSTRUCTIONS_CLOSE_TAG"]
        )
    if recipe == "spawn_agent_raw_templates":
        source = source.split("fn spawn_agent_tool_description(", 1)[1].split(
            "fn spawn_agent_tool_description_v2(", 1
        )[0]
        values = raw_strings(source)
        require(len(values) == 3, "expected three upstream spawn-agent templates")
        return dict(
            zip(
                ("tool_description", "with_usage_hint", "description"),
                values,
                strict=True,
            )
        )
    if recipe == "builtin_agent_descriptions":
        source = source.split("mod built_in {", 1)[1].split(
            "// Awaiter is temp removed", 1
        )[0]
        default = re.search(
            r'description: Some\(("(?:[^"\\]|\\.)*")\.to_string\(\)\)', source
        )
        result = {"default": {"description": rust_string(default[1])}}
        for name, description in re.findall(
            r'"(explorer|worker)"\.to_string\(\),\s*AgentRoleConfig\s*\{\s*description: Some\(r#"([\s\S]*?)"#\.to_string\(\)\)',
            source,
        ):
            result[name] = {"description": description}
        require(len(result) == 3, "expected three built-in upstream agent roles")
        return result
    if recipe == "mcp_resource_tool_specs":
        result = {}
        for block in source.split("pub fn create_")[1:]:
            name = rust_string(re.search(r'name:\s*("(?:[^"\\]|\\.)*")', block)[1])
            description = rust_string(
                re.search(r'description:\s*("(?:[^"\\]|\\.)*")', block)[1]
            )
            properties = {}
            for key, value in re.findall(
                r'("(?:[^"\\]|\\.)*")\.to_string\(\),\s*JsonSchema::string\(Some\(\s*("(?:[^"\\]|\\.)*")',
                block,
            ):
                properties[rust_string(key)] = {
                    "type": "string",
                    "description": rust_string(value),
                }
            parameters = {
                "type": "object",
                "properties": dict(sorted(properties.items())),
                "additionalProperties": False,
            }
            if name == "read_mcp_resource":
                parameters["required"] = ["server", "uri"]
            result[name] = {
                "type": "function",
                "name": name,
                "description": description,
                "strict": False,
                "parameters": parameters,
            }
        require(len(result) == 3, "expected three MCP resource specs")
        return result
    raise ValueError(f"unknown derivation recipe: {recipe}")


def verify(core, reference, *, offline=False):
    manifest = json.loads((core / "UPSTREAM.json").read_text())
    baseline = json.loads((reference / "UPSTREAM.json").read_text())
    for name, expected in {
        "repository": REPOSITORY,
        "version": VERSION,
        "tag": TAG,
        "commit": COMMIT,
    }.items():
        require(
            manifest.get(name) == expected, f"Python provenance {name} is not pinned"
        )
        require(baseline.get(name) == expected, f"reference {name} is not pinned")
    require(
        manifest.get("implementation") == "python-semantic-port",
        "incorrect implementation kind",
    )
    require(
        manifest.get("claims_full_behavioral_equivalence") is False,
        "semantic-equivalence claim is unsupported",
    )
    lock_bytes = (reference / "Cargo.lock").read_bytes()
    require(
        sha256(lock_bytes) == baseline["files"]["Cargo.lock"]["sha256"],
        "reference Cargo.lock changed",
    )
    lock = tomllib.loads(lock_bytes.decode())
    dependencies = {entry["name"]: entry for entry in manifest["dependencies"]}
    require(
        set(dependencies) == set(PINNED_DEPENDENCIES),
        "dependency provenance inventory differs",
    )
    archives = {}
    for name, (version, checksum) in PINNED_DEPENDENCIES.items():
        dependency = dependencies[name]
        require(
            dependency["version"] == version and dependency["checksum"] == checksum,
            f"dependency is not pinned: {name}",
        )
        require(
            any(
                row["name"] == name
                and row["version"] == version
                and row.get("checksum") == checksum
                for row in lock["package"]
            ),
            f"dependency differs from fixed Cargo.lock: {name}",
        )
        archives[name] = crate_archive(name, version, checksum, offline)
    require(
        set(manifest["modules"])
        == {path.name for pattern in ("*.py", "*.js") for path in core.glob(pattern)},
        "Python module inventory differs from provenance mapping",
    )
    for name, module in manifest["modules"].items():
        require(
            module["kind"] in {"semantic-port", "framework-integration"},
            f"invalid module kind: {name}",
        )
        require(
            module["sources"] or module["kind"] == "framework-integration",
            f"missing upstream source mapping: {name}",
        )
        for source in module["sources"]:
            require(
                source in manifest["sources"], f"unrecorded source for {name}: {source}"
            )
    source_bytes = {}
    for source, record in manifest["sources"].items():
        if source.startswith("crate://"):
            name, version, member = source.removeprefix("crate://").split("/", 2)
            require(
                name in dependencies and dependencies[name]["version"] == version,
                f"source outside fixed dependencies: {source}",
            )
            with tarfile.open(fileobj=io.BytesIO(archives[name])) as archive:
                file = archive.extractfile(f"{name}-{version}/{member}")
                require(file is not None, f"missing crate source: {source}")
                data = file.read()
            require(
                sha256(data) == record["sha256"],
                f"crate source hash mismatch: {source}",
            )
            source_bytes[source] = data
            continue
        path = record["reference_path"]
        upstream = baseline["files"].get(path)
        require(
            upstream is not None and upstream["upstream_path"] == source,
            f"source is outside fixed reference: {source}",
        )
        require(
            upstream["upstream_sha256"] == record["sha256"],
            f"source baseline hash mismatch: {source}",
        )
        data = (reference / path).read_bytes()
        require(sha256(data) == record["sha256"], f"reference source changed: {source}")
        source_bytes[source] = data
    actual_assets = {
        str(path.relative_to(core))
        for directory in (
            "assets",
            "context_assets",
            "resource_assets",
            "tool_assets",
            "memory_assets",
            "code_mode_assets",
        )
        for path in (core / directory).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } | {"LICENSE", "NOTICE"}
    require(
        actual_assets == set(manifest["assets"]) | METADATA,
        "asset inventory differs from provenance mapping",
    )
    copied = derived = 0
    for path, record in manifest["assets"].items():
        data = (core / path).read_bytes()
        require(sha256(data) == record["sha256"], f"asset hash mismatch: {path}")
        sources = [source_bytes[name] for name in record["sources"]]
        if record["kind"] == "byte-copy":
            require(
                len(sources) == 1 and data == sources[0],
                f"copied asset differs from upstream: {path}",
            )
            copied += 1
        elif record["kind"] == "derived-data":
            actual = json.loads(data) if path.endswith(".json") else data.decode()
            require(
                actual == derive(record["recipe"], sources),
                f"derived asset differs from upstream: {path}",
            )
            derived += 1
        else:
            raise ValueError(f"invalid asset kind: {path}")
    for path in METADATA:
        metadata = json.loads((core / path).read_text())
        require(
            metadata["commit"] == COMMIT and metadata["tag"] == TAG,
            f"auxiliary manifest is not pinned: {path}",
        )
        records = metadata["files"]
        records = (
            records.items()
            if isinstance(records, dict)
            else ((row["path"], row) for row in records)
        )
        for name, record in records:
            expected = record if isinstance(record, str) else record["sha256"]
            require(
                sha256((core / Path(path).parent / name).read_bytes()) == expected,
                f"auxiliary asset hash mismatch: {path}:{name}",
            )
    return f"Verified {len(manifest['modules'])} core source mappings, {copied} byte copies, {derived} derived assets at {TAG} ({COMMIT}). Semantic equivalence is not established by this check."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument(
        "--reference", type=Path, default=DEFAULT_CORE.parent / "runtime"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Require pinned crate archives to be cached locally",
    )
    args = parser.parse_args()
    try:
        print(
            verify(args.core.resolve(), args.reference.resolve(), offline=args.offline)
        )
    except (ValueError, KeyError, OSError, TypeError, IndexError) as error:
        parser.exit(1, f"Codex Python provenance verification failed: {error}\n")


if __name__ == "__main__":
    main()
