"""Run either native harness over a fresh local copy of the public corpus."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory


def bind(agent, benchmark):
    value = benchmark.config.get("corpus_path")
    if not value:
        raise ValueError(
            "OfficeQA-Pro requires benchmark.corpus_path with public corpus documents"
        )
    corpus = Path(value).expanduser().resolve()
    if not corpus.is_dir():
        raise ValueError("benchmark.corpus_path must be a public corpus directory")
    # Only the corpus is staged. A question/answer CSV in the parent directory
    # must not accidentally become part of the Agent's searchable workspace.
    documents = tuple(p for p in sorted(corpus.rglob("*")) if p.is_file())
    if not documents or any(
        p.is_symlink() or p.suffix.lower() not in (".txt", ".md", ".pdf", ".json")
        for p in documents
    ):
        raise ValueError(
            "corpus_path must contain only public txt/md/pdf/json documents"
        )

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("OfficeQA-Pro requires a loaded benchmark Task")
        with TemporaryDirectory(prefix="flashrsi-officeqa-") as temporary:
            root = Path(temporary)
            destination = root / "corpus"
            # Copy, rather than link, so candidate edits cannot contaminate later runs.
            for path in documents:
                copied = destination / path.relative_to(corpus)
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, copied)
            return await target.run(
                task.question + "\n\nCorpus: ./corpus", working_dir=root
            )

    agent._env_runner = run
