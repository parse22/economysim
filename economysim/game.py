"""Interactive turn-based game: you choose each action."""

from __future__ import annotations

from .model import (
    Config,
    State,
    advancement,
    action_costs,
    camp_yield,
    describe,
    legal_actions,
    position_name,
    start,
    step,
)

HELP = """\
Each turn, pick an action by number. Every action spends time; most spend attrition.
An action fails if its attrition cost would drain your pool to 0 (full attrition).
Commands: number = act, s = status of objectives, h = help, q = quit."""


def status_line(cfg: Config, s: State) -> str:
    camps = ""
    if cfg.growth == "finite":
        camps = f" | Camps left {max(0, cfg.camp_count - s.camps)}"
    elif cfg.growth == "diminishing":
        camps = f" | Next camp +{camp_yield(cfg, s)}"
    return (
        f"Time {s.time}/{cfg.time} | Attrition {s.attrition}/{cfg.attrition} | "
        f"Growth {s.growth} | Advancement {advancement(s)}/{len(cfg.objectives)} "
        f"(ramp +{cfg.ramp(advancement(s))}){camps} | At: {position_name(cfg, s.pos)}"
    )


def objectives_table(cfg: Config, s: State) -> str:
    rows = []
    for i, o in enumerate(cfg.objectives):
        state = "done" if s.done >> i & 1 else f"challenge {o.difficulty + cfg.ramp(advancement(s))}"
        rows.append(f"  {i + 1}. {o.name:<12} {state:<14} time {o.time}, +{o.growth} growth")
    return "\n".join(rows)


def option_line(cfg: Config, s: State, a) -> str:
    t, cost = action_costs(cfg, s, a)
    warn = ""
    if t > s.time:
        warn = "  << runs out of time"
    elif cost >= s.attrition:
        warn = "  << FAILS (full attrition)"
    return f"{describe(cfg, s, a):<48} time -{t}, attrition -{cost}{warn}"


def run(cfg: Config, input=input, print=print) -> State:
    print(f"Encounter economy: {cfg.fundamentals()}")
    print(HELP)
    print(objectives_table(cfg, start(cfg)))
    s = start(cfg)
    while s.status == "active":
        print()
        print(status_line(cfg, s))
        actions = legal_actions(cfg, s)
        for n, a in enumerate(actions, 1):
            print(f"  {n}) {option_line(cfg, s, a)}")
        choice = input("> ").strip().lower()
        if choice in ("q", "quit"):
            print("Session abandoned.")
            return s
        if choice in ("h", "help", "?"):
            print(HELP)
            continue
        if choice == "s":
            print(objectives_table(cfg, s))
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(actions):
            print("Pick a listed number.")
            continue
        result = step(cfg, s, actions[int(choice) - 1])
        print(f"-> {result.message}")
        s = result.state
    print()
    print(status_line(cfg, s))
    print(f"Session {'WON' if s.status == 'won' else 'LOST'}: {s.end}.")
    return s
