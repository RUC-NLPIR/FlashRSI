"""Retry malformed fast-stage replies without replacing original request caches.

Retries use the identical prompt and role config, inside the original logical
call, so parallel scheduling never consumes additional Worker ordinals. Each
completed retry is stored separately and reused on replay. Slow/meta retain the
frozen rejection behavior; no patch text is repaired or fabricated locally.
"""

from __future__ import annotations

import json
from dataclasses import replace

from flashrsi._records import _config_record, _trajectory_record
from flashrsi.agents import LLM
from flashrsi.algorithms.skillopt._patch import _json, _Patch, _PatchError
from scripts._context_safe_worker import ContextSafeLLM
from scripts._experiment_runtime import _digest, _restore, _save_cache

POLICY = "retry_malformed_fast_reply_twice_same_prompt_v1"


def _validate(prompt, output):
    if prompt.startswith(
        ("[SkillOpt: failure]", "[SkillOpt: success]", "[SkillOpt: merge]")
    ):
        _Patch.parse(output)
    elif prompt.startswith("[SkillOpt: rank]"):
        _json(output)


class ProtocolSafeLLM(ContextSafeLLM):
    async def run(self, prompt, working_dir=None):
        ordinal = self._experiment_worker_ordinal
        original = await super().run(prompt, working_dir)
        try:
            _validate(prompt, original.output)
            return original
        except _PatchError as error:
            initial_error = str(error)

        key = _digest(
            {
                "policy": POLICY,
                "ordinal": ordinal,
                "prompt": prompt,
                "config": _config_record(self.config),
                "original_output": original.output,
            }
        )
        directory = self._experiment_cache_dir / "protocol_retries" / self.name / key
        # Also bound retries across process restarts; valid retry records are not
        # copied into the original cache or counted twice by the report.
        for attempt in (1, 2):
            path = directory / f"{attempt}.json"
            if path.exists():
                record = json.loads(path.read_text())
                if record["key"] != key or record["policy"] != POLICY:
                    raise ValueError("Incompatible protocol retry record")
                result = _restore(record["trajectory"], None)
            else:
                async with self._cache_state().semaphore:
                    result = await LLM.run(self, prompt)
                record = {
                    "key": key,
                    "policy": POLICY,
                    "run_ordinal": ordinal,
                    "attempt": attempt,
                    "original_output_sha256": _digest(original.output),
                    "initial_error": initial_error,
                    "trajectory": _trajectory_record(result),
                }
                _save_cache(path, record, self.config)
                print(
                    f"[worker] protocol retry {attempt}/2 for ordinal {ordinal}: "
                    f"{result.status}",
                    flush=True,
                )
            if result.status != "finished":
                continue
            try:
                _validate(prompt, result.output)
            except _PatchError:
                continue
            return replace(
                result,
                messages=(
                    *result.messages,
                    {
                        "type": "ProtocolRecovery",
                        "policy": POLICY,
                        "run_ordinal": ordinal,
                        "initial_error": initial_error,
                        "original_output_sha256": _digest(original.output),
                        "retry_record": str(path),
                        "completed_retries": attempt,
                    },
                ),
            )
        raise RuntimeError(
            f"Worker protocol recovery exhausted after 2 attempts; evidence: {directory}"
        )
