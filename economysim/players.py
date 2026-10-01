"""Ways of choosing actions: optimal search and player archetypes."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, NamedTuple, Optional

from .model import (
    CAMP,
    ENGAGE,
    REST,
    ROTATE,
    Action,
    Config,
    State,
    Step,
    advancement,
    available_objectives,
    camp_yield,
    challenge,
    legal_actions,
    start,
    step,
)

Decide = Callable[[Config, State], Action]


class Run(NamedTuple):
    final: State
    steps: list[Step]
    actions: list[Action]

    @property
    def failures(self) -> int:
        return sum(s.failed for s in self.steps)

    def count(self, cfg: Config, kind: int) -> int:
        """Completed engagements at CAMP or REST."""
        n = 0
        s = start(cfg)
        for a, st in zip(self.actions, self.steps):
            if a.kind == ENGAGE and s.pos == kind and not st.failed:
                n += 1
            s = st.state
        return n


def play(cfg: Config, decide: Decide) -> Run:
    s = start(cfg)
    steps, actions = [], []
    while s.status == "active":
        a = decide(cfg, s)
        st = step(cfg, s, a)
        steps.append(st)
        actions.append(a)
        s = st.state
    return Run(s, steps, actions)


def score(s: State) -> tuple:
    """Rank terminal states for the optimal player.

    A win ranks above any loss, then by leftover time, attrition and growth.
    Leftover time and attrition mean nothing after a loss, so losses rank by
    advancement, then growth, then running out of time over elimination.
    """
    if s.status == "won":
        return (1, advancement(s), s.time, s.attrition, s.growth)
    return (0, advancement(s), s.growth, int(s.end == "time"), 0)


def solve(cfg: Config) -> Run:
    """Best achievable outcome by exhaustive search (perfect information)."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10 * cfg.time + 1000))

    def key(s: State) -> State:
        # The failure count never affects play, and under renewable growth
        # neither does the camp counter.
        s = s._replace(failures=0)
        return s._replace(camps=0) if cfg.growth == "renewable" else s

    @lru_cache(maxsize=None)
    def best(s: State) -> tuple[tuple, Optional[Action]]:
        actions = legal_actions(cfg, s)
        if not actions:
            return score(s), None
        return max(((best(key(step(cfg, s, a, check=False).state))[0], a) for a in actions), key=lambda x: x[0])

    return play(cfg, lambda cfg, s: best(key(s))[1])


@dataclass(frozen=True)
class Archetype:
    """A rule-based player.

    grow_until: camp while the next objective would cost more than this
        fraction of max attrition. None never camps for that reason.
    camp_after_failure: camp once for every failure (the rusher's only
        reason to camp).
    rest_below: rest whenever attrition is below this fraction of max.

    Every archetype also rests before an encounter it cannot afford, or that
    would leave too little attrition to rotate back to a rest site, but only
    when resting would actually change the outcome. If even a full pool
    cannot pay for the encounter, it attacks anyway and accepts the failure.
    """

    name: str
    grow_until: Optional[float]
    rest_below: float
    camp_after_failure: bool = False
    summary: str = ""

    def __call__(self, cfg: Config, s: State) -> Action:
        options = available_objectives(cfg, s)
        target = min(options, key=lambda i: challenge(cfg, s, i))
        cost = cfg.cost(challenge(cfg, s, target), s.growth)

        can_rest = cfg.rest_sites > 0 and s.attrition < cfg.attrition
        if can_rest and s.attrition < self.rest_below * cfg.attrition:
            return _toward(s, REST)

        if camp_yield(cfg, s) > 0:
            owed = self.camp_after_failure and s.failures > s.camps
            wants = self.grow_until is not None and cost > self.grow_until * cfg.attrition
            if owed or wants:
                target, cost = CAMP, cfg.cost(cfg.camp_challenge, s.growth)

        if can_rest:
            # From a rest site at full attrition: rotate, then the encounter.
            after_rest = cfg.attrition - cfg.rotation_attrition - cost
            if after_rest > 0:
                travel = 0 if s.pos == target else cfg.rotation_attrition
                need = cost + travel
                if after_rest > cfg.rotation_attrition:
                    need += cfg.rotation_attrition  # keep enough to get back
                if s.attrition <= need:
                    return _toward(s, REST)
        return _toward(s, target)


def _toward(s: State, target: int) -> Action:
    return Action(ENGAGE) if s.pos == target else Action(ROTATE, target)


ARCHETYPES = {
    a.name: a
    for a in (
        Archetype("rusher", grow_until=None, rest_below=0.0, camp_after_failure=True,
                  summary="always attacks; camps once after each failure"),
        Archetype("balanced", grow_until=0.5, rest_below=0.25,
                  summary="camps until objectives cost half the pool"),
        Archetype("cautious", grow_until=0.25, rest_below=0.5,
                  summary="camps until objectives are cheap; rests below half"),
    )
}
