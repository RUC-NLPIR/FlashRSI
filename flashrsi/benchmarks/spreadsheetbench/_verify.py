"""Private container entry point using the pinned official cell comparison."""

import json
from pathlib import Path

from evaluation import compare_workbooks
from open_spreadsheet import find_libreoffice, just_open_libreoffice


def main():
    root = Path(__file__).parent
    record = json.loads((root / "record.json").read_text())
    output = Path("/logs/artifacts") / record["output_name"]
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError("SpreadsheetBench output must be a regular workbook")
    soffice = find_libreoffice()
    if not soffice:
        raise RuntimeError("LibreOffice is required for SpreadsheetBench evaluation")
    golden = root / "golden.xlsx"
    if not just_open_libreoffice(str(golden), soffice):
        raise RuntimeError("Golden workbook recalculation failed")
    correct = False
    if output.is_file() and just_open_libreoffice(str(output), soffice):
        correct, _ = compare_workbooks(
            str(golden),
            str(output),
            record["instruction_type"],
            record["answer_position"],
        )
    # Do not publish the official comparator's detailed reference-cell values.
    log = Path("/logs/verifier")
    log.mkdir(parents=True, exist_ok=True)
    (log / "reward.json").write_text(json.dumps({"reward": float(correct)}))


if __name__ == "__main__":
    main()
