"""Call the native UNO helper; fail if it silently leaves a workbook unchanged."""

import os
import sys
from pathlib import Path


def recalculate(files):
    import open_spreadsheet

    # The native helper catches per-file errors. A sentinel timestamp lets us
    # detect those failures without changing its calculation/save implementation.
    for file in files:
        os.utime(file, ns=(1_000_000_000, 1_000_000_000))
    if not open_spreadsheet.start_libreoffice_service():
        raise RuntimeError("Cannot start native LibreOffice service")
    try:
        open_spreadsheet.batch_open_files([str(p) for p in files])
        for file in files:
            if Path(file).stat().st_mtime_ns == 1_000_000_000:
                raise RuntimeError(f"Native LibreOffice recalculation failed: {file}")
    finally:
        open_spreadsheet.stop_libreoffice_service()


if __name__ == "__main__":
    recalculate([Path(p) for p in sys.argv[1:]])
