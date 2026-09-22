"""EvoPrompt: evolve a population of prompts, by GA or by DE.

    _initialize  the target's own instruction, then paraphrases of it, all scored
    _ga / _de    one generation, repeated max_steps times
    _promote     adopt the fittest member, once, at the end

Fitness is always a dev score: `_member` is the only place a prompt becomes a
candidate Snapshot, and it evaluates every one it builds.

Upstream: https://github.com/microsoft/EvoPrompt (ICLR 2024, arXiv:2309.08532)
Commit: 2e235c9410e38d531dabfae7fdd9cbded1577373
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

from flashrsi.algorithms.evoprompt import _prompts as prompts
from flashrsi.core import Algorithm, Snapshot
from flashrsi.core.snapshot import _matching_components, _validate_path

#: The smallest population each variant can run: GA draws two parents per
#: child, DE a target plus three distinct donors.
_MINIMUM = {"ga": 2, "de": 4}
_SELECTION = ("wheel", "random", "tournament")
_SURVIVORS = ("topk", "standard")


@dataclass(frozen=True, slots=True)
class Member:
    """One population member and the dev fitness that admitted it.

    The text is carried beside the snapshot because every operator reads it: a
    crossover prompt quotes two members verbatim, and top-k survivor selection
    deduplicates on the text rather than on the snapshot.
    """

    snapshot: Snapshot
    text: str
    score: float
    #: True when an operator returned nothing usable and this slot kept its
    #: parent's files and fitness. Recorded so a reader of the decision log can
    #: tell that from a candidate that genuinely scored the same.
    carried: bool = False


class EvoPrompt(Algorithm):
    """GA or DE population evolution over one instruction file.

    The two variants differ in *when* a member is displaced. GA builds a whole
    child population and then decides which of parents and children survive, so
    a good parent can be lost to a better child from another lineage. DE keeps
    the population positionally: a trial competes only against the target it was
    built from, and every other member is untouched.

    Neither variant moves the current version during the search: the population
    carries every member's fitness throughout, so one promotion at the end is
    enough and every member was scored against the same baseline.
    """

    name = "evoprompt"
    description = "Evolve a population of prompts by GA or DE."
    evolve_scope = {"prompt"}
    observation_scope = {"prompt"}
    _defaults = {
        # Published EvoPrompt runs 10 generations over a population of 10.
        "variant": "ga",
        "population_size": 10,
        "max_steps": 10,
        # GA only; DE draws its donors uniformly, as upstream does.
        "selection": "wheel",
        "survivor_selection": "topk",
        # Upstream's DE uses the global-best base vector unless --donor_random.
        "donor_random": False,
        "seed": 42,
    }

    async def evolve(self) -> Snapshot:
        current = self.target.snapshot
        await self._initialize(current)

        generation = self._ga if self.config.variant == "ga" else self._de
        for step in range(self.config.max_steps):
            await generation(random.Random(self.config.seed + step), step)

        return self._promote(current)

    async def _initialize(self, seed: Snapshot) -> None:
        """Seed the population: the target's own instruction, then paraphrases.

        The starting snapshot is already a member, so it is evaluated as it is
        rather than patched to its own text -- which would propose a candidate
        that changes nothing.
        """
        text = self._read_text(seed).get(self._path, "")
        results = await self._evaluate(seed, self.benchmark.dev, label="baseline")
        self._population = [Member(seed, text, _mean(results, self._metric))]
        self._baseline = self._population[0].score

        while len(self._population) < self.config.population_size:
            reply = await self._ask(
                prompts.INITIALIZE.format(path=self._path, seed=text),
                label="paraphrase",
            )
            self._population.append(
                await self._member(self._population[0], _prompt(reply), label="seed")
            )

    async def _ga(self, rng: random.Random, step: int) -> None:
        """Build a full child population, then decide which members survive.

        ``wheel`` resamples the population fitness-proportionately first, so the
        same member can legitimately be drawn as both parents of a child; the
        other policies draw from the population itself. Survivor selection is
        then the whole decision: a child not selected is simply never adopted.
        """
        pool = (
            _wheel(self._population, rng, self.config.population_size)
            if self.config.selection == "wheel"
            else tuple(self._population)
        )
        children = []
        for _ in range(self.config.population_size):
            first, second = self._parents(rng, pool)
            reply = await self._ask(
                prompts.GA.format(
                    path=self._path, prompt1=first.text, prompt2=second.text
                ),
                label="crossover",
            )
            children.append(await self._member(first, _prompt(reply), label="child"))

        size = self.config.population_size
        survivors = (
            tuple(children)
            if self.config.survivor_selection == "standard"
            else _top_k(tuple(self._population) + tuple(children), size)
        )
        self._adopt(step, survivors, children)

    async def _de(self, rng: random.Random, step: int) -> None:
        """One trial per target, accepted by strict pairwise replacement."""
        current = tuple(self._population)
        base = max(current, key=lambda member: member.score)

        survivors, trials = [], []
        for position, target in enumerate(current):
            # Donors are drawn by position, which is what DE means: upstream
            # walks the population's indices and a trial competes with the
            # member at its own slot. Filtering by identity instead would also
            # couple this loop to _member's internals.
            others = [item for index, item in enumerate(current) if index != position]
            first, second, third = rng.sample(others, 3)
            reply = await self._ask(
                prompts.DE.format(
                    path=self._path,
                    prompt0=target.text,
                    prompt1=first.text,
                    prompt2=second.text,
                    prompt3=(third if self.config.donor_random else base).text,
                ),
                label="mutate",
            )
            trial = await self._member(target, _prompt(reply), label="trial")
            trials.append(trial)
            # A trial competes only with the target it was built from, so a
            # losing one leaves the rest of the population where it was.
            survivors.append(trial if trial.score > target.score else target)
        self._adopt(step, tuple(survivors), trials)

    def _promote(self, current: Snapshot) -> Snapshot:
        """Select once, at the end: the current version never moved.

        Every member was therefore scored against the same baseline, which is
        why the whole population is recorded rather than a sequence of
        accept/reject decisions.
        """
        best = max(self._population, key=lambda member: member.score)
        self._record(
            "decision",
            {
                "kind": "promote",
                "parent_id": current.id,
                "candidate_id": best.snapshot.id,
                "path": self._path,
                "score": best.score,
                "baseline_score": self._baseline,
                "accepted": best.snapshot.id != current.id,
                "population": [_row(member) for member in self._population],
            },
        )
        if best.snapshot.id != current.id:
            self.target.update(best.snapshot)
        return self.target.snapshot

    # -- the pieces a generation is built from -----------------------------

    async def _member(self, parent: Member, text: str, *, label: str) -> Member:
        """Commit one prompt as a candidate and score it on dev.

        Every fitness in the population comes from here. An operator that
        returned nothing usable, or the parent's own text back, keeps the
        parent's snapshot and fitness: re-scoring the same files would spend a
        dev pass to learn nothing. It still becomes its own record, so a
        population slot never aliases another slot's member -- top-k pads from
        the ranked pool by excluding the entries it already took, and an alias
        would remove the fitter member's every copy at once.
        """
        if not text or text == parent.text:
            return Member(parent.snapshot, parent.text, parent.score, carried=True)
        candidate = self._candidate(parent.snapshot, {self._path: text})
        results = await self._evaluate(candidate, self.benchmark.dev, label=label)
        return Member(candidate, text, _mean(results, self._metric))

    def _parents(self, rng: random.Random, pool: tuple[Member, ...]):
        """Two parents for one child, by the configured policy."""
        if self.config.selection != "tournament":
            return rng.sample(list(pool), 2)
        # A binary tournament per parent, which is what upstream's ``tour``
        # policy runs: sample two, keep the fitter.
        return [
            max(rng.sample(list(pool), 2), key=lambda member: member.score)
            for _ in range(2)
        ]

    def _adopt(
        self, step: int, survivors: tuple[Member, ...], candidates: list[Member]
    ) -> None:
        """Adopt a generation's survivors and record what it displaced."""
        self._record(
            "decision",
            {
                "kind": "generation",
                "variant": self.config.variant,
                "step": step,
                "candidates": [_row(member) for member in candidates],
                "population": [_row(member) for member in survivors],
            },
        )
        self._population = list(survivors)

    @property
    def _metric(self) -> str:
        return self.benchmark.primary_metric

    def _check(self) -> None:
        if not self.benchmark.dev:
            raise ValueError("EvoPrompt requires a non-empty dev split")
        # The target names the file it loads its instructions from, so a run
        # needs no knowledge of the harness's layout and no algorithm branches
        # on the harness name.
        path = self.target.instruction_file
        if not isinstance(path, str) or not path:
            raise ValueError(
                f"{self.target.name} declares no instruction_file, so EvoPrompt "
                "has nothing to rewrite"
            )
        _validate_path(path)
        rules = self.target.component_rules
        if _matching_components(path, rules) != {"prompt"}:
            patterns = ", ".join(rules.get("prompt", ()))
            raise ValueError(
                f"{self.target.name} declares an instruction_file outside its "
                f"prompt component ({patterns}), which EvoPrompt cannot evolve: "
                f"{path}"
            )
        self._path = path
        variant = self.config.variant
        if variant not in _MINIMUM:
            raise ValueError("algorithm.variant must be one of: " + ", ".join(_MINIMUM))
        # Upstream's CLI calls tournament selection ``tour``. Accept that
        # spelling and canonicalize it here, so the loop compares against one
        # name and the saved configuration records what actually ran.
        if self.config.selection == "tour":
            self.config.selection = "tournament"
        if self.config.selection not in _SELECTION:
            raise ValueError(
                "algorithm.selection must be one of: " + ", ".join(_SELECTION)
            )
        if self.config.survivor_selection not in _SURVIVORS:
            raise ValueError(
                "algorithm.survivor_selection must be one of: " + ", ".join(_SURVIVORS)
            )
        for key in ("population_size", "max_steps", "seed"):
            if type(self.config[key]) is not int:
                raise ValueError(f"algorithm.{key} must be an integer")
        if self.config.max_steps < 1:
            raise ValueError("algorithm.max_steps must be an integer >= 1")
        if self.config.population_size < _MINIMUM[variant]:
            raise ValueError(
                f"EvoPrompt {variant} needs algorithm.population_size >= "
                f"{_MINIMUM[variant]}"
            )
        if type(self.config.donor_random) is not bool:
            raise ValueError("algorithm.donor_random must be a boolean")


def _wheel(
    population: list[Member], rng: random.Random, size: int
) -> tuple[Member, ...]:
    """Fitness-proportionate resampling with replacement (roulette wheel).

    Weights fall back to uniform when every fitness is zero, which is the
    ordinary state of a freshly initialized population and would otherwise make
    ``random.choices`` raise instead of sampling.
    """
    weights = [member.score for member in population]
    return tuple(
        rng.choices(population, weights=weights if sum(weights) > 0 else None, k=size)
    )


def _top_k(pool: tuple[Member, ...], size: int) -> tuple[Member, ...]:
    """The best distinct prompts in ``pool``, padded back to a fixed size.

    Deduplicating on the text is what makes this top-k rather than a plain sort:
    a generation whose mutations collapsed onto one prompt would otherwise fill
    the whole population with copies of it. The padding is equally load-bearing
    -- the next generation still needs ``size`` members to draw parents from, so
    the best remaining duplicates come back in.
    """
    best: dict[str, Member] = {}
    for member in pool:
        previous = best.get(member.text)
        if previous is None or member.score > previous.score:
            best[member.text] = member
    ranked = sorted(pool, key=lambda member: member.score, reverse=True)
    survivors = tuple(
        sorted(best.values(), key=lambda member: member.score, reverse=True)
    )[:size]
    chosen = {id(member) for member in survivors}
    survivors += tuple(member for member in ranked if id(member) not in chosen)[
        : size - len(survivors)
    ]
    while len(survivors) < size:
        survivors += (ranked[len(survivors) % len(ranked)],)
    return survivors


def _mean(results, metric: str) -> float:
    # An empty dev split cannot reach here: _check rejects it first.
    return math.fsum(item.metrics[metric] for item in results) / len(results)


def _row(member: Member) -> dict:
    row = {
        "snapshot_id": member.snapshot.id,
        "text": member.text,
        "score": member.score,
    }
    # Only marked when true, so an ordinary candidate's row stays as it was.
    if member.carried:
        row["carried"] = True
    return row


def _prompt(reply: str) -> str:
    """Read the new prompt out of a tagged reply.

    Every upstream template ends by asking for the result "bracketed with
    <prompt> and </prompt>", and each one also *shows* that bracketing in its
    worked example. So the last closed pair wins: a reply that quotes the
    request back would otherwise be read from the example's tag.

    The text becomes a file's whole content, so it ends with a newline.
    """
    found = re.findall(r"<prompt>(.*?)</prompt>", reply, flags=re.DOTALL)
    text = (found[-1] if found else reply).strip()
    return text + "\n" if text else text


__all__ = ["EvoPrompt"]
