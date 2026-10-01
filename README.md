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

## Web version

`web/index.html` is a phone-friendly page with three tabs: Play (the
interactive game), Compare (one configuration at a time: optimal play
against the three archetypes, with a timeline of how each spent its time and
step-by-step traces)
and Settings (every parameter, plus JSON import and export).
`web/economysim.js` is a JavaScript port of the model and players.
`tests/test_web_parity.py` runs both versions on the same configurations and
fails if any run differs, so change them together. To use the page locally,
serve the `web/` folder (`python -m http.server -d web`) and open it in a
browser.

## Players

- **optimal**: exhaustive search with perfect information; the best outcome
  the configuration permits.
- **rusher** (always attacks; camps once after each failure), **balanced**,
  **cautious**: rule-based archetypes
  (`economysim/players.py`).

## Layout

| File                     | Contents                                   |
|--------------------------|--------------------------------------------|
| `economysim/model.py`    | Config, state, legal actions, step rules   |
| `economysim/players.py`  | Optimal search and archetypes              |
| `economysim/game.py`     | Interactive game                           |
| `economysim/__main__.py` | Command line                               |
| `web/`                   | Web page and JavaScript port of the model  |
| `tests/`                 | `python -m unittest` (parity test needs Node) |
