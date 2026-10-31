"""Built-in benchmark implementations."""

from flashrsi.benchmarks.aime import AIME
from flashrsi.benchmarks.alfworld import ALFWorld
from flashrsi.benchmarks.appworld import AppWorldBenchmark
from flashrsi.benchmarks.bbeh import BBEH
from flashrsi.benchmarks.bfcl import BFCL
from flashrsi.benchmarks.browsecomp import BrowseComp
from flashrsi.benchmarks.deepsearchqa import DeepSearchQA
from flashrsi.benchmarks.deepswe import DeepSWE
from flashrsi.benchmarks.harvey_lab import HarveyLAB
from flashrsi.benchmarks.hle import HLE
from flashrsi.benchmarks.hotpotqa import HotpotQA
from flashrsi.benchmarks.jobbench import JobBench
from flashrsi.benchmarks.livemathbench import LiveMathBench
from flashrsi.benchmarks.math import MATH
from flashrsi.benchmarks.musique import MuSiQue
from flashrsi.benchmarks.nq import NQ
from flashrsi.benchmarks.officeqa_pro import OfficeQAPro
from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.benchmarks.spreadsheetbench2 import SpreadsheetBench2
from flashrsi.benchmarks.supergpqa import SuperGPQA
from flashrsi.benchmarks.swe_bench import SWEBench
from flashrsi.benchmarks.swe_bench_pro import SWEBenchPro
from flashrsi.benchmarks.tau2 import Tau2Benchmark
from flashrsi.benchmarks.tau3_banking import Tau3Banking
from flashrsi.benchmarks.terminal_bench import TerminalBench
from flashrsi.benchmarks.travelplanner import TravelPlanner
from flashrsi.benchmarks.triviaqa import TriviaQA
from flashrsi.benchmarks.twowiki_multihopqa import TwoWikiMultiHopQA
from flashrsi.benchmarks.widesearch import WideSearch
from flashrsi.benchmarks.workbench import WorkBench

__all__ = [
    "ALFWorld",
    "Tau2Benchmark",
    "AIME",
    "BBEH",
    "SuperGPQA",
    "TwoWikiMultiHopQA",
    "TravelPlanner",
    "HarveyLAB",
    "BFCL",
    "BrowseComp",
    "DeepSearchQA",
    "DeepSWE",
    "HLE",
    "MATH",
    "OfficeQAPro",
    "JobBench",
    "LiveMathBench",
    "AppWorldBenchmark",
    "NQ",
    "SWEBench",
    "SWEBenchPro",
    "HotpotQA",
    "MuSiQue",
    "SearchQA",
    "SpreadsheetBench2",
    "Tau3Banking",
    "TerminalBench",
    "TriviaQA",
    "WideSearch",
    "WorkBench",
]
