"""Command line: matrix, solve and play."""

from __future__ import annotations

import argparse
import json

from . import game
from .model import CAMP, FAILURE_MODES, GROWTH_MODES, REST, SEQUENCE_MODES, Config, advancement, position_name
from .players import ARCHETYPES, Run, play, solve


def load_config(args) -> Config:
    cfg = Config.load(args.config) if args.config else Config()
    return cfg.with_fundamentals(args.failure, args.sequence, args.growth)


def outcome(cfg: Config, run: Run) -> str:
    s = run.final
    if s.status == "won":
        return f"won, {s.time} time left"
    return f"lost ({s.end}), {advancement(s)}/{len(cfg.objectives)}"


def summary(cfg: Config, run: Run) -> str:
    return (f"camps {run.count(cfg, CAMP)}, rests {run.count(cfg, REST)}, "
            f"failures {run.failures}, growth {run.final.growth}")


def cmd_matrix(args) -> None:
    base = Config.load(args.config) if args.config else Config()
    names = list(ARCHETYPES)
    header = ["fundamentals", "optimal", "optimal play"] + names
    rows = []
    for f in FAILURE_MODES:
        for q in SEQUENCE_MODES:
            for g in GROWTH_MODES:
                cfg = base.with_fundamentals(f, q, g)
                best = solve(cfg)
                row = [cfg.fundamentals(), outcome(cfg, best), summary(cfg, best)]
                row += [outcome(cfg, play(cfg, ARCHETYPES[n])) for n in names]
                rows.append(row)
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(len(header))]
    for r in [header, ["-" * w for w in widths]] + rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    print()
    for n, a in ARCHETYPES.items():
        print(f"{n}: {a.summary}")


def cmd_run(args) -> None:
    cfg = load_config(args)
    run = solve(cfg) if args.player == "optimal" else play(cfg, ARCHETYPES[args.player])
    print(f"{cfg.fundamentals()} — {args.player}")
    for st in run.steps:
        n = st.state
        print(f"  {st.message:<58} time {n.time:>3}  attrition {n.attrition:>2}  growth {n.growth:>2}  "
              f"adv {advancement(n)}  at {position_name(cfg, n.pos)}")
    print(f"Result: {outcome(cfg, run)}; {summary(cfg, run)}")


def cmd_play(args) -> None:
    try:
        game.run(load_config(args))
    except (EOFError, KeyboardInterrupt):
        print("\nSession abandoned.")


def cmd_config(args) -> None:
    print(json.dumps(load_config(args).to_dict(), indent=2))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="economysim", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, func, help, fundamentals=True):
        p = sub.add_parser(name, help=help)
        p.add_argument("--config", help="JSON file overriding default parameters")
        if fundamentals:
            p.add_argument("--failure", choices=FAILURE_MODES)
            p.add_argument("--sequence", choices=SEQUENCE_MODES)
            p.add_argument("--growth", choices=GROWTH_MODES)
        p.set_defaults(func=func)
        return p

    add("matrix", cmd_matrix, "compare all 12 fundamental configurations", fundamentals=False)
    run = add("run", cmd_run, "trace one configuration with the optimal player or an archetype")
    run.add_argument("--player", default="optimal", choices=["optimal", *ARCHETYPES])
    add("play", cmd_play, "play one configuration interactively")
    add("config", cmd_config, "print the effective configuration as JSON")

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
