"""Command-line configuration and experiment preparation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

import yaml

from flashrsi.config import _ConfigLoader, load_config, prepare_run_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        normalized = _dotted_args(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        parser.error(str(exc))
    args, unknown = parser.parse_known_args(normalized)
    if unknown:
        parser.error("Unrecognized arguments; use 'flashrsi run --help' for usage.")
    try:
        config = load_config(args.config, overrides=_overrides(args))
    except ValueError as exc:
        if isinstance(exc.__cause__, yaml.YAMLError):
            parser.error("Invalid YAML in configuration file; check its syntax.")
        parser.error(str(exc))
    except OSError as exc:
        parser.error(str(exc))

    if not args.prepare_only:
        parser.error(
            "Experiment execution is not implemented yet. "
            "Use --prepare-only to validate configuration and create a run directory."
        )

    try:
        run_dir = prepare_run_dir(config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(f"Prepared experiment: {run_dir}")
    print(f"Configuration: {run_dir / 'config.yaml'}")
    print("Preparation only; no tasks or model calls were run.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flashrsi", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run",
        help="Configure an experiment",
        allow_abbrev=False,
        epilog=(
            "Any configuration field accepts --path.to.key VALUE or --path.to.key=VALUE, "
            "e.g. --algorithm.worker.llm.temperature 0.7. Values use YAML syntax. "
            "Dotted options and --set override named flags; the last setting wins."
        ),
    )
    run.add_argument(
        "--config", "-c", metavar="PATH", help="Read configuration from YAML"
    )
    run.add_argument("--benchmark", help="Override benchmark.name")
    run.add_argument("--algorithm", help="Override algorithm.name")
    run.add_argument("--agent", help="Override agent.name")
    run.add_argument("--model", help="Override agent.llm.model_name")
    run.add_argument("--worker-model", help="Override algorithm.worker.llm.model_name")
    run.add_argument("--output-dir", metavar="PATH", help="Override run.output_dir")
    run.add_argument(
        "--set",
        dest="settings",
        metavar="PATH=VALUE",
        action="append",
        default=[],
        help="Set a dotted configuration path to a YAML value; repeat for more settings",
    )
    run.add_argument(
        "--prepare-only",
        action="store_true",
        help="Validate configuration and create a run directory without executing tasks",
    )
    return parser


def _dotted_args(argv: Sequence[str]) -> list[str]:
    """Normalize dotted flags to --set while preserving setting order."""
    result = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            result.extend(argv[index:])
            break
        flag, separator, value = arg.partition("=")
        if flag == "--set" and not separator:
            # Its payload is a single argument, not another option to normalize.
            result.extend(argv[index : index + 2])
            index += 2
            continue
        if flag.startswith("--") and "." in flag:
            if not separator:
                index += 1
                if index >= len(argv) or _looks_like_option(argv[index]):
                    raise ValueError(f"{flag} requires a value; use {flag}=VALUE")
                value = argv[index]
            result.extend(["--set", f"{flag[2:]}={value}"])
        else:
            result.append(arg)
        index += 1
    return result


def _looks_like_option(value: str) -> bool:
    if not value.startswith("-"):
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    fields = {
        "benchmark": "benchmark.name",
        "algorithm": "algorithm.name",
        "agent": "agent.name",
        "model": "agent.llm.model_name",
        "worker_model": "algorithm.worker.llm.model_name",
        "output_dir": "run.output_dir",
    }
    for flag, path in fields.items():
        value = getattr(args, flag)
        if value is not None:
            _set_value(result, path, value)

    for setting in args.settings:
        path, separator, raw_value = setting.partition("=")
        if not separator:
            raise ValueError("--set requires PATH=VALUE, e.g. algorithm.rounds=3")
        try:
            value = yaml.load(raw_value, Loader=_ConfigLoader)
        except (yaml.YAMLError, ValueError):
            # Parser diagnostics may include a credential supplied as the value.
            raise ValueError(f"Invalid YAML value for --set {path}") from None
        _set_value(result, path, value)
    return result


def _set_value(values: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if any(not part or part != part.strip() for part in parts):
        raise ValueError("--set paths must contain non-empty dot-separated keys")
    current = values
    for index, part in enumerate(parts[:-1]):
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            parent = ".".join(parts[: index + 1])
            raise ValueError(f"Cannot set {path}: {parent} is not a mapping")
    current[parts[-1]] = value
