"""Encounter economy model. The rules are specified in docs/spec.md."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from typing import NamedTuple, Optional

FAILURE_MODES = ("elimination", "delay")
SEQUENCE_MODES = ("fixed", "free")
GROWTH_MODES = ("renewable", "finite", "diminishing")
RAMP_KINDS = ("none", "linear", "table")
COST_KINDS = ("linear", "curve")
TIME_SCALING_KINDS = ("none", "curve")

# Positions. Objectives are positions 0..N-1.
NOWHERE = -1  # between locations, e.g. after clearing a camp or objective
CAMP = -2     # at an uncleared camp
REST = -3     # at a rest site

ROTATE = "rotate"
ENGAGE = "engage"


@dataclass(frozen=True)
class Objective:
    name: str
    difficulty: int
    time: int
    growth: int


@dataclass(frozen=True)
class Ramp:
    """Challenge added at Advancement k."""

    kind: str = "linear"  # "none": 0; "linear": rate * k; "table": table[k], last value repeats
    rate: int = 3
    table: tuple[int, ...] = ()

    def __call__(self, k: int) -> int:
        if self.kind == "none":
            return 0
        if self.kind == "linear":
            return self.rate * k
        if self.kind == "table":
            return self.table[min(k, len(self.table) - 1)] if self.table else 0
        raise ValueError(f"unknown ramp kind {self.kind!r}")


def _ipow(x: float, n: int) -> float:
    """x ** n for a whole n >= 0, by repeated multiplication (matches the web port exactly)."""
    r = 1.0
    for _ in range(n):
        r *= x
    return r


@dataclass(frozen=True)
class Cost:
    """Attrition drained by an encounter of challenge C at Growth G.

    The gap is C - G: positive when underleveled, negative when overleveled.

    linear: max(floor, round(scale * gap)).
    curve: RPG-style. At an even match (gap 0) the cost is `base`. Each point
        of underlevelling multiplies the cost by `under`, so wide gaps head
        towards impossible. Each point of overlevelling keeps only `over` of
        the remaining cost above `floor`, so overlevelling has diminishing
        returns.
    """

    kind: str = "linear"
    floor: int = 1
    scale: float = 1.0
    base: float = 2.0
    under: float = 1.2
    over: float = 0.6

    def __call__(self, challenge: int, growth: int) -> int:
        gap = challenge - growth
        if self.kind == "linear":
            return max(self.floor, round(self.scale * gap))
        if self.kind == "curve":
            if gap >= 0:
                value = self.base * _ipow(self.under, gap)
            else:
                value = self.floor + (self.base - self.floor) * _ipow(self.over, -gap)
            return max(self.floor, round(value))
        raise ValueError(f"unknown cost kind {self.kind!r}")


@dataclass(frozen=True)
class TimeScaling:
    """Multiplier on an encounter's base time from the gap C - G.

    none: always the base time.
    curve: each point of underlevelling multiplies time by `under`; each point
        of overlevelling keeps `over` of the remaining distance to the
        `fastest` multiplier, so overlevelling has diminishing returns.
    Scaled time is rounded and never below 1.
    """

    kind: str = "none"
    under: float = 1.1
    over: float = 0.85
    fastest: float = 0.5

    def __call__(self, base_time: int, challenge: int, growth: int) -> int:
        if self.kind == "none":
            return base_time
        if self.kind == "curve":
            gap = challenge - growth
            if gap >= 0:
                m = _ipow(self.under, gap)
            else:
                m = self.fastest + (1 - self.fastest) * _ipow(self.over, -gap)
            return max(1, round(base_time * m))
        raise ValueError(f"unknown time scaling kind {self.kind!r}")


DEFAULT_OBJECTIVES = (
    Objective("Outpost", difficulty=5, time=3, growth=1),
    Objective("Watchtower", difficulty=7, time=3, growth=1),
    Objective("Fortress", difficulty=9, time=4, growth=1),
    Objective("Citadel", difficulty=11, time=5, growth=0),
)


@dataclass(frozen=True)
class Config:
    # Fundamentals
    failure: str = "elimination"
    sequence: str = "fixed"
    growth: str = "renewable"

    # Session
    time: int = 75
    attrition: int = 12
    objectives: tuple[Objective, ...] = DEFAULT_OBJECTIVES

    # Camp
    camp_time: int = 3
    camp_challenge: int = 5
    camp_yield: int = 4
    camp_count: int = 3   # finite: camps available per session
    camp_decay: int = 1   # diminishing: yield of the nth camp is camp_yield - decay * n

    # Rest
    rest_time: int = 3
    rest_restore: int = 6
    rest_sites: int = 1

    # Rotation
    rotation_time: int = 2
    rotation_attrition: int = 1

    # Curves
    ramp: Ramp = field(default_factory=Ramp)
    # How the gap between challenge and growth sets attrition and time.
    objective_time_scaling: TimeScaling = field(default_factory=TimeScaling)
    camp_time_scaling: TimeScaling = field(default_factory=TimeScaling)
    # Camp challenge scaling with Advancement, separate from objectives.
    camp_ramp: Ramp = field(default_factory=lambda: Ramp(kind="none", rate=1))
    cost: Cost = field(default_factory=Cost)

    # Delay variants
    delay_time: int = 8
    delay_recover: int = 6
    delay_growth_loss: int = 0
    delay_retry: bool = True
    delay_relocate: bool = False

    def __post_init__(self) -> None:
        for name, allowed in (
            ("failure", FAILURE_MODES),
            ("sequence", SEQUENCE_MODES),
            ("growth", GROWTH_MODES),
        ):
            if getattr(self, name) not in allowed:
                raise ValueError(f"{name} must be one of {allowed}")
        if not self.objectives:
            raise ValueError("at least one objective is required")
        times = [self.camp_time, self.rest_time, self.rotation_time]
        if min(times + [o.time for o in self.objectives]) < 1:
            raise ValueError("every encounter must cost at least 1 time")
        if self.delay_recover < 1:
            raise ValueError("delay_recover must be at least 1")
        for name in ("ramp", "camp_ramp"):
            if getattr(self, name).kind not in RAMP_KINDS:
                raise ValueError(f"{name} kind must be one of {RAMP_KINDS}")
        if self.cost.kind not in COST_KINDS:
            raise ValueError(f"cost kind must be one of {COST_KINDS}")
        if self.cost.kind == "curve":
            c = self.cost
            if not (c.under >= 1 and 0 < c.over <= 1 and c.base >= c.floor):
                raise ValueError("cost curve needs under >= 1, 0 < over <= 1 and base >= floor")
        for name in ("objective_time_scaling", "camp_time_scaling"):
            t = getattr(self, name)
            if t.kind not in TIME_SCALING_KINDS:
                raise ValueError(f"{name} kind must be one of {TIME_SCALING_KINDS}")
            if t.kind == "curve" and not (t.under >= 1 and 0 < t.over <= 1 and 0 < t.fastest <= 1):
                raise ValueError(f"{name} needs under >= 1, 0 < over <= 1 and 0 < fastest <= 1")

    def fundamentals(self) -> str:
        return f"{self.failure}/{self.sequence}/{self.growth}"

    def with_fundamentals(self, failure=None, sequence=None, growth=None) -> "Config":
        return replace(
            self,
            failure=failure or self.failure,
            sequence=sequence or self.sequence,
            growth=growth or self.growth,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        data = dict(data)
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        if "objectives" in data:
            data["objectives"] = tuple(Objective(**o) for o in data["objectives"])
        for key in ("ramp", "camp_ramp"):
            if key in data:
                ramp = dict(data[key])
                ramp["table"] = tuple(ramp.get("table", ()))
                data[key] = Ramp(**ramp)
        if "cost" in data:
            data["cost"] = Cost(**data["cost"])
        for key in ("objective_time_scaling", "camp_time_scaling"):
            if key in data:
                data[key] = TimeScaling(**data[key])
        return cls(**data)

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict:
        return asdict(self)


class State(NamedTuple):
    time: int
    attrition: int
    growth: int = 0
    done: int = 0         # bitmask of completed objectives
    pos: int = NOWHERE
    camps: int = 0        # camps used so far
    failures: int = 0     # encounters failed through full attrition
    status: str = "active"  # "active" | "won" | "lost"
    end: str = ""         # why the session ended


class Action(NamedTuple):
    kind: str                      # ROTATE or ENGAGE
    target: Optional[int] = None   # ROTATE destination: CAMP, REST or an objective index


class Step(NamedTuple):
    state: State
    time: int        # time spent by the encounter
    cost: int        # attrition the encounter required
    failed: bool     # full attrition
    message: str


def start(cfg: Config) -> State:
    return State(time=cfg.time, attrition=cfg.attrition)


def advancement(s: State) -> int:
    return bin(s.done).count("1")


def all_done(cfg: Config) -> int:
    return (1 << len(cfg.objectives)) - 1


def challenge(cfg: Config, s: State, i: int) -> int:
    return cfg.objectives[i].difficulty + cfg.ramp(advancement(s))


def camp_challenge(cfg: Config, s: State) -> int:
    return cfg.camp_challenge + cfg.camp_ramp(advancement(s))


def camp_yield(cfg: Config, s: State) -> int:
    if cfg.growth == "finite":
        return cfg.camp_yield if s.camps < cfg.camp_count else 0
    if cfg.growth == "diminishing":
        return max(0, cfg.camp_yield - cfg.camp_decay * s.camps)
    return cfg.camp_yield


def available_objectives(cfg: Config, s: State) -> list[int]:
    remaining = [i for i in range(len(cfg.objectives)) if not s.done >> i & 1]
    return remaining if cfg.sequence == "free" else remaining[:1]


def position_name(cfg: Config, pos: int) -> str:
    if pos == NOWHERE:
        return "on the road"
    if pos == CAMP:
        return "Camp"
    if pos == REST:
        return "Rest site"
    return cfg.objectives[pos].name


def legal_actions(cfg: Config, s: State) -> list[Action]:
    if s.status != "active":
        return []
    actions = []
    if s.pos == CAMP or s.pos >= 0 or (s.pos == REST and s.attrition < cfg.attrition):
        actions.append(Action(ENGAGE))
    for i in available_objectives(cfg, s):
        if s.pos != i:
            actions.append(Action(ROTATE, i))
    if s.pos != CAMP and camp_yield(cfg, s) > 0:
        actions.append(Action(ROTATE, CAMP))
    if s.pos != REST and cfg.rest_sites > 0:
        actions.append(Action(ROTATE, REST))
    return actions


def action_costs(cfg: Config, s: State, a: Action) -> tuple[int, int]:
    """(time, attrition) an action requires in state s."""
    if a.kind == ROTATE:
        return cfg.rotation_time, cfg.rotation_attrition
    if s.pos == CAMP:
        c = camp_challenge(cfg, s)
        return cfg.camp_time_scaling(cfg.camp_time, c, s.growth), cfg.cost(c, s.growth)
    if s.pos == REST:
        return cfg.rest_time, 0
    c = challenge(cfg, s, s.pos)
    return cfg.objective_time_scaling(cfg.objectives[s.pos].time, c, s.growth), cfg.cost(c, s.growth)


def describe(cfg: Config, s: State, a: Action) -> str:
    if a.kind == ROTATE:
        if a.target >= 0:
            return f"Rotate to {cfg.objectives[a.target].name} (challenge {challenge(cfg, s, a.target)})"
        return f"Rotate to {position_name(cfg, a.target)}"
    if s.pos == CAMP:
        return f"Camp (+{camp_yield(cfg, s)} growth)"
    if s.pos == REST:
        return f"Rest (+{min(cfg.rest_restore, cfg.attrition - s.attrition)} attrition)"
    obj = cfg.objectives[s.pos]
    return f"Take {obj.name} (+{obj.growth} growth, +1 advancement)"


def _end(s: State, status: str, end: str) -> State:
    return s._replace(status=status, end=end)


def step(cfg: Config, s: State, a: Action, check: bool = True) -> Step:
    """Apply one action. Raises ValueError if the action is illegal (when check is set)."""
    if check and a not in legal_actions(cfg, s):
        raise ValueError(f"illegal action {a} in {s}")
    t, cost = action_costs(cfg, s, a)
    label = describe(cfg, s, a)
    time = s.time - t
    if time < 0:
        n = s._replace(time=0)
        return Step(_end(n, "lost", "time"), t, cost, False, f"{label}: ran out of time")

    if cost >= s.attrition:
        return _full_attrition(cfg, s._replace(time=time), a, t, cost, label)

    n = s._replace(time=time, attrition=s.attrition - cost)
    if a.kind == ROTATE:
        n = n._replace(pos=a.target)
    elif s.pos == CAMP:
        n = n._replace(growth=n.growth + camp_yield(cfg, s), camps=s.camps + 1, pos=NOWHERE)
    elif s.pos == REST:
        n = n._replace(attrition=min(cfg.attrition, s.attrition + cfg.rest_restore))
    else:
        obj = cfg.objectives[s.pos]
        n = n._replace(growth=n.growth + obj.growth, done=s.done | 1 << s.pos, pos=NOWHERE)

    if n.done == all_done(cfg):
        n = _end(n, "won", "all objectives complete")
    elif n.time == 0:
        n = _end(n, "lost", "time")
    return Step(n, t, cost, False, label)


def _full_attrition(cfg: Config, s: State, a: Action, t: int, cost: int, label: str) -> Step:
    msg = f"{label}: FAILED, full attrition"
    s = s._replace(failures=s.failures + 1)
    if cfg.failure == "elimination":
        return Step(_end(s._replace(attrition=0), "lost", "eliminated"), t, cost, True, msg + ", eliminated")

    engaged = a.kind == ENGAGE
    if engaged and s.pos >= 0 and not cfg.delay_retry:
        lost = _end(s._replace(attrition=0), "lost", "objective lost")
        return Step(lost, t, cost, True, msg + ", objective lost")

    n = s._replace(
        time=max(0, s.time - cfg.delay_time),
        attrition=min(cfg.attrition, cfg.delay_recover),
        growth=max(0, s.growth - cfg.delay_growth_loss),
    )
    if engaged and s.pos == CAMP and not cfg.delay_retry:
        n = n._replace(camps=n.camps + 1, pos=NOWHERE)
    if cfg.delay_relocate:
        n = n._replace(pos=NOWHERE)
    msg += f", delayed {cfg.delay_time} time"
    if cfg.delay_growth_loss:
        msg += f", lost {cfg.delay_growth_loss} growth"
    if n.time == 0:
        n = _end(n, "lost", "time")
    return Step(n, t, cost, True, msg)
