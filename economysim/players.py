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
    # Win first, then advancement, then leftover time, attrition and growth.
    return (s.status == "won", advancement(s), s.time, s.attrition, s.growth)


def solve(cfg: Config) -> Run:
    """Best achievable outcome by exhaustive search (perfect information)."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10 * cfg.time + 1000))

    def key(s: State) -> State:
        # Under renewable growth the camp counter never affects play.
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
        fraction of max attrition. None never camps.
    rest_below: rest whenever attrition is below this fraction of max.
        Independently, always rest unless the next encounter leaves enough
        attrition to rotate back to a rest site.
    """

    name: str
    grow_until: Optional[float]
    rest_below: float
    summary: str = ""

    def __call__(self, cfg: Config, s: State) -> Action:
        options = available_objectives(cfg, s)
        target = min(options, key=lambda i: challenge(cfg, s, i))
        need = cfg.cost(challenge(cfg, s, target), s.growth)

        can_rest = cfg.rest_sites > 0 and s.attrition < cfg.attrition
        if can_rest and s.attrition < self.rest_below * cfg.attrition:
            return _toward(s, REST)

        if self.grow_until is not None and need > self.grow_until * cfg.attrition and camp_yield(cfg, s) > 0:
            target, need = CAMP, cfg.cost(cfg.camp_challenge, s.growth)

        if s.pos != target:
            need += cfg.rotation_attrition
        if cfg.rest_sites > 0:
            need += cfg.rotation_attrition
        if can_rest and s.attrition <= need:
            return _toward(s, REST)
        return _toward(s, target)


def _toward(s: State, target: int) -> Action:
    return Action(ENGAGE) if s.pos == target else Action(ROTATE, target)


ARCHETYPES = {
    a.name: a
    for a in (
        Archetype("rusher", grow_until=None, rest_below=0.0,
                  summary="never camps; rests only to avoid failing"),
        Archetype("balanced", grow_until=0.5, rest_below=0.25,
                  summary="camps until objectives cost half the pool"),
        Archetype("cautious", grow_until=0.25, rest_below=0.5,
                  summary="camps until objectives are cheap; rests below half"),
    )
}
