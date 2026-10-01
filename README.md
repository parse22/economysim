# economysim

An abstract, turn-based simulator for testing the fundamentals of a roguelike
(Nightreign-style) encounter economy: Camp, Objective, Rest and Rotation
trading Time, Attrition, Growth and Advancement.

The rules are specified in [docs/spec.md](docs/spec.md).

Pure Python 3.10+, no dependencies.

## Fundamentals

| Question                                   | Options                             |
|--------------------------------------------|-------------------------------------|
| Does full attrition lead to delay or elimination? | `--failure elimination\|delay`     |
| Is objective sequence fixed or free?       | `--sequence fixed\|free`            |
| Is growth renewable, finite or diminishing?| `--growth renewable\|finite\|diminishing` |

Everything else is a parameter; see `python -m economysim config`.

## Usage

```sh
# Compare all 12 fundamental configurations: optimal play and each archetype
python -m economysim matrix

# Trace one configuration, step by step
python -m economysim run --sequence free --growth diminishing
python -m economysim run --failure delay --player balanced

# Play one configuration yourself
python -m economysim play --failure delay --sequence free --growth finite

# Print the effective parameters as JSON (a starting point for --config)
python -m economysim config > my.json
python -m economysim matrix --config my.json
```

A `--config` file only needs the keys it overrides, for example:

```json
{
  "time": 90,
  "ramp": {"kind": "table", "table": [0, 2, 6, 12]},
  "delay_growth_loss": 2
}
```

## Players

- **optimal**: exhaustive search with perfect information; the best outcome
  the configuration permits.
- **rusher**, **balanced**, **cautious**: rule-based archetypes
  (`economysim/players.py`).

## Layout

| File                     | Contents                                   |
|--------------------------|--------------------------------------------|
| `economysim/model.py`    | Config, state, legal actions, step rules   |
| `economysim/players.py`  | Optimal search and archetypes              |
| `economysim/game.py`     | Interactive game                           |
| `economysim/__main__.py` | Command line                               |
| `tests/`                 | `python -m unittest`                       |
