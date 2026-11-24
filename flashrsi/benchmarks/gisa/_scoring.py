"""Use the unmodified, pinned official GISA evaluator on host-side references."""

import importlib.util
from functools import lru_cache

from flashrsi.benchmarks._source_file import source_file

REVISION = "8b05d80811f8f474d154e35496fc620807adf3f4"
SHA256 = "6c80c9114cca001d353adeed7627fc2108e0f46eb70f970d16fcf25bbaa73c0a"


@lru_cache(maxsize=1)
def evaluator():
    path = source_file(
        f"https://raw.githubusercontent.com/RUC-NLPIR/GISA/{REVISION}/eval_script/run_evaluation.py",
        SHA256,
    )
    spec = importlib.util.spec_from_file_location("_flashrsi_gisa_evaluation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SimpleEvaluator()


def score(prediction, reference, answer_type):
    # The upstream CLI also accepts a host CSV pathname. A model answer must
    # always be parsed as text; appending a newline disables that file shortcut.
    return evaluator().evaluate_one(prediction + "\n", str(reference), answer_type)
