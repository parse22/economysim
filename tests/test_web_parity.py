"""Check that web/economysim.js matches the Python model run for run."""

import json
import shutil
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path

from economysim.model import FAILURE_MODES, GROWTH_MODES, SEQUENCE_MODES, Config, Cost, Ramp
from economysim.players import ARCHETYPES, play, solve

JS = Path(__file__).resolve().parent.parent / "web" / "economysim.js"

NODE_SCRIPT = """
const sim = require(process.argv[1]);
const configs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = configs.map(cfg => {
  const runs = {optimal: sim.solve(cfg)};
  for (const [n, a] of Object.entries(sim.ARCHETYPES)) runs[n] = sim.play(cfg, a);
  const res = {};
  for (const [n, r] of Object.entries(runs))
    res[n] = {messages: r.steps.map(s => s.message), final: r.final};
  return res;
});
process.stdout.write(JSON.stringify({defaults: sim.defaultConfig(), runs: out}));
"""


def python_runs(cfg):
    runs = {"optimal": solve(cfg), **{n: play(cfg, a) for n, a in ARCHETYPES.items()}}
    return {
        n: {"messages": [s.message for s in r.steps], "final": r.final._asdict()}
        for n, r in runs.items()
    }


def configs():
    base = Config()
    for f in FAILURE_MODES:
        for q in SEQUENCE_MODES:
            for g in GROWTH_MODES:
                yield base.with_fundamentals(f, q, g)
    # Parameter variants, on a few configurations where they take effect.
    variants = [
        replace(base, delay_growth_loss=2, delay_relocate=True, time=60),
        replace(base, delay_retry=False, attrition=10),
        replace(base, ramp=Ramp(kind="table", table=(0, 2, 7, 9)), cost=Cost(floor=2, scale=1.5)),
        replace(base, camp_ramp=Ramp(kind="linear", rate=2), time=90),
        replace(base, camp_ramp=Ramp(kind="table", table=(0, 1, 3)), ramp=Ramp(kind="none")),
    ]
    for v in variants:
        yield v.with_fundamentals("delay", "free", "finite")
        yield v.with_fundamentals("delay", "fixed", "diminishing")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class WebParity(unittest.TestCase):
    def test_js_matches_python(self):
        cfgs = list(configs())
        proc = subprocess.run(
            ["node", "-e", NODE_SCRIPT, str(JS)],
            input=json.dumps([c.to_dict() for c in cfgs]),
            capture_output=True, text=True, check=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["defaults"], json.loads(json.dumps(Config().to_dict())))
        for cfg, js in zip(cfgs, result["runs"]):
            self.assertEqual(js, python_runs(cfg), cfg.fundamentals())
