"""Run a selected JiuwenSwarm source tree through its native Process SDK."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from flashrsi._records import _redact, _secrets
from flashrsi.agents.jiuwenswarm._sdk import Client
from flashrsi.core import Agent, Trajectory

_ENTRY = Path(__file__).with_name("_entry.py")


class JiuwenSwarm(Agent):
    """Keep native execution and skills; version files independently of sessions."""

    name = "jiuwenswarm"
    description = "JiuwenSwarm single Agent with versioned native source and skills."

    def _check_container(self) -> None:
        wheels = self.config.get("container_wheels")
        if not wheels or (
            not hasattr(self, "_container_source_dir")
            and not any(Path(wheels).glob("workswarm-*.whl"))
        ):
            raise ValueError(
                "JiuwenSwarm requires agent.container_wheels with a workswarm wheel"
            )

    async def _run(self, prompt: str, working_dir: Path | None = None) -> Trajectory:
        config = self.config
        llm = config.get("llm", {})
        # Never fall back to the user's native model catalog or environment keys.
        if not all(llm.get(key) for key in ("model_name", "base_url", "api_key")):
            raise ValueError(
                "JiuwenSwarm requires explicit llm.model_name, base_url and api_key"
            )
        mode = config.get("mode", "agent.work.normal")
        if mode not in ("agent.work.normal", "agent.code.normal"):
            raise ValueError("JiuwenSwarm supports only single-Agent normal modes")
        files = self.files_dir
        secrets = sorted(
            set(_secrets(os.environ) + _secrets(config)), key=len, reverse=True
        )
        timeout = config.get("timeout", 300)
        python = (
            str(Path(config["python"]).expanduser().resolve())
            if config.get("python") and not hasattr(self, "_container_source_dir")
            else sys.executable
        )
        with TemporaryDirectory(prefix="flashrsi-jiuwenswarm-") as temporary:
            root = Path(temporary)
            task_dir = working_dir or root / "task"
            task_dir.mkdir(parents=True, exist_ok=True)
            data_dir = root / "data"
            native = yaml.safe_load((files / "config.yaml").read_text(encoding="utf-8"))
            active = native.pop("active_harness_packages", [])
            if (
                not isinstance(active, list)
                or any(
                    not isinstance(name, str) or not name.isidentifier()
                    for name in active
                )
                or len(active) != len(set(active))
            ):
                raise ValueError(
                    "active_harness_packages must list unique Python package names"
                )
            manifests = []
            for name in active:
                package = files / "runtime/openjiuwen/extensions/harness" / name
                manifest = package / "harness_config.yaml"
                if not (package / "__init__.py").is_file() or not manifest.is_file():
                    raise ValueError(f"Incomplete Snapshot harness package: {name}")
                manifests.append(str(manifest.resolve()))
            if active:
                registry = data_dir / "infra/auto-harness/harness-packages.json"
                registry.parent.mkdir(parents=True)
                registry.write_text(
                    json.dumps(
                        {
                            "active_package_ids": active,
                            "packages": [
                                {
                                    "id": name,
                                    "extension_name": name,
                                    "config_path": path,
                                }
                                for name, path in zip(active, manifests)
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
            # Connection state belongs to this invocation, never to the Snapshot.
            native["models"] = {
                "defaults": [
                    {
                        "model_id": "flashrsi",
                        "is_default": True,
                        "model_client_config": {
                            "model_name": llm["model_name"],
                            "api_base": llm["base_url"],
                            "api_key": "${FLASHRSI_JIUWEN_API_KEY}",
                            "client_provider": llm.get("provider", "OpenAI"),
                            "endpoint_profile": llm.get(
                                "endpoint_profile", "openai_compatible"
                            ),
                            "supports_vision": False,
                        },
                        "model_config_obj": {
                            key: value
                            for key, value in llm.items()
                            if key
                            not in {
                                "model_name",
                                "base_url",
                                "api_key",
                                "provider",
                                "endpoint_profile",
                            }
                        },
                    }
                ],
                "groups": [],
                "agentos": [],
            }
            config_dir = data_dir / "infra/config"
            config_dir.mkdir(parents=True)
            (config_dir / "config.yaml").write_text(
                yaml.safe_dump(native, allow_unicode=True), encoding="utf-8"
            )
            messages = []

            async def observe(event):
                messages.append(_redact(event, secrets))

            client = Client(
                [
                    python,
                    "-I",
                    "-B",
                    str(_ENTRY),
                    str(files),
                ],
                cwd=str(task_dir),
            )
            # The SDK's constructor merges env with os.environ. Supply its
            # process env explicitly so old credentials cannot reach tools.
            client.env = {
                key: value
                for key, value in os.environ.items()
                if not _secrets({key: value})
                and not key.startswith("FLASHRSI_")
                and key not in {"API_BASE", "MODEL_NAME", "MODEL_PROVIDER"}
            }
            client.env.update(
                {
                    "JIUWENSWARM_DATA_DIR": str(data_dir),
                    "FLASHRSI_JIUWEN_API_KEY": llm["api_key"],
                    "PYTHONUTF8": "1",
                }
            )
            if active:
                receipt = root / "loaded-packages.json"
                client.env["FLASHRSI_JIUWEN_PACKAGE_RECEIPT"] = str(receipt)
            request = {
                "input": prompt,
                "mode": mode,
                "model": llm["model_name"],
                "workspace": {
                    "cwd": str(task_dir),
                    "project_dir": str(task_dir),
                    "trusted_dirs": [str(task_dir)],
                },
                "timeout_seconds": timeout,
                "max_turns": config.get("max_turns", 10),
            }
            if "skills" in config:
                request["skills"] = list(config["skills"])
            try:
                result = await client.run(
                    request, on_event=observe, deadline_seconds=timeout + 60
                )
            except Exception as error:
                return Trajectory(
                    status="error",
                    messages=messages,
                    error_message=_redact(
                        f"JiuwenSwarm {type(error).__name__}: {error}", secrets
                    ),
                )
            result = _redact(result, secrets)
            success = result["status"] == "completed"
            if success and active:
                loaded = (
                    json.loads(receipt.read_text(encoding="utf-8"))
                    if receipt.is_file()
                    else {}
                )
                if list(loaded) != manifests:
                    return Trajectory(
                        status="error",
                        messages=messages,
                        error_message=f"Native activation not confirmed for {active}",
                    )
                messages.append(
                    {
                        "type": "HarnessPackagesLoaded",
                        "packages": active,
                        "resources": {
                            name: loaded[path] for name, path in zip(active, manifests)
                        },
                    }
                )
            usage = dict(result.get("usage", {}))
            # Native model_calls is a count; FlashRSI uses that name for a list.
            if "model_calls" in usage:
                usage["model_call_count"] = usage.pop("model_calls")
            return Trajectory(
                status="finished" if success else "error",
                output=result.get("output") or "",
                messages=messages,
                usage=usage,
                error_message=None
                if success
                else json.dumps(result.get("error"), ensure_ascii=False),
            )
