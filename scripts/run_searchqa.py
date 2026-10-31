"""Compatibility entry; existing SearchQA commands use the general launcher."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiment import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main(default_config="searchqa.local.yaml"))
    except KeyboardInterrupt:
        sys.exit(130)
