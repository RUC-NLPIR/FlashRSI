"""Resolve model labels for archived runs and explicitly documented corrections."""

import json
from pathlib import Path


def model_labels(config, *, key, harness, benchmark, initial, selected):
    worker = config.get("algorithm", {}).get("worker", {})
    labels = {
        "targetModel": config.get("agent", {}).get("llm", {}).get("model_name"),
        "workerModel": worker.get("llm", {}).get("model_name"),
    }
    if all(value and value != "Not recorded" for value in labels.values()):
        return labels
    directory = Path(__file__).resolve().parents[1] / "examples/experiments"
    corrections = json.loads(
        (directory / "model-metadata.json").read_text(encoding="utf-8")
    )
    name = f"{key}-{harness}-{benchmark}"
    correction = corrections.get(name)
    if correction and (
        correction["initialId"], correction["selectedId"]
    ) == (initial, selected):
        for role in labels:
            if not labels[role] or labels[role] == "Not recorded":
                labels[role] = correction[role]
    return {role: value or "Not recorded" for role, value in labels.items()}
