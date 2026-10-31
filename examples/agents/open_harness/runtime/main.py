"""Tiny executable harness: use this version's skill to answer the prompt."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
answer = (root / "skills/main.md").read_text(encoding="utf-8").strip()
print(f"{answer} ({sys.argv[1]})")
