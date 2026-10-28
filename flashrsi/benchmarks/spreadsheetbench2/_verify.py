"""Container entry point: preserve native scoring and publish Harbor rewards."""

import json
from pathlib import Path

from _recalculate import recalculate
from evaluation import process_single_item


def main():
    root = Path(__file__).parent
    record = json.loads((root / "record.json").read_text())
    row, category = record["row"], record["category"]
    originals = [
        root / row[key] for key in ("spreadsheet_path", "golden_response_path")
    ]
    recalculate(originals)
    output = Path("/logs/artifacts") / f"{row['id']}_output.xlsx"
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError(
            "SpreadsheetBench2 output must be a regular workbook, not a symlink"
        )
    if output.is_file():
        recalculate([output])
    result, _ = process_single_item(row, str(root), str(output.parent), {}, category)
    log = Path("/logs/verifier")
    log.mkdir(parents=True, exist_ok=True)
    (log / "native-result.json").write_text(json.dumps(result))
    (log / "reward.json").write_text(
        json.dumps(
            {
                "reward": result["accuracy"],
                "regression_accuracy": result["regression_accuracy"],
                "modification_accuracy": result["modification_accuracy"],
            }
        )
    )


if __name__ == "__main__":
    main()
