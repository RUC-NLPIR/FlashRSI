"""Built-in evolution algorithms.

Additional algorithms imported from https://github.com/ignorejjj/FlashRSI-Lite
at d8d5e35e77e1c0360a1df55505db3cfb2b113cd0. Existing local ports are retained.
"""

from flashrsi.algorithms.ace import ACE
from flashrsi.algorithms.adas import ADAS
from flashrsi.algorithms.ahe import AHE
from flashrsi.algorithms.darwinx import DarwinX
from flashrsi.algorithms.evo_harness import EvoHarness
from flashrsi.algorithms.evoprompt import EvoPrompt
from flashrsi.algorithms.gepa import GEPA
from flashrsi.algorithms.meta_harness import MetaHarness
from flashrsi.algorithms.modular_rsi import ModularRSI
from flashrsi.algorithms.opro import OPRO
from flashrsi.algorithms.rrsi import RRSI
from flashrsi.algorithms.skillopt import SkillOpt

__all__ = [
    "ACE",
    "ADAS",
    "AHE",
    "DarwinX",
    "EvoHarness",
    "EvoPrompt",
    "GEPA",
    "MetaHarness",
    "ModularRSI",
    "OPRO",
    "RRSI",
    "SkillOpt",
]
