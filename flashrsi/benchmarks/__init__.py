"""Built-in benchmark implementations."""

from flashrsi.benchmarks.hotpotqa import HotpotQA
from flashrsi.benchmarks.searchqa import SearchQA
from flashrsi.benchmarks.tau3_banking import Tau3Banking
from flashrsi.benchmarks.terminal_bench import TerminalBench

__all__ = ["HotpotQA", "SearchQA", "Tau3Banking", "TerminalBench"]
