import unittest

from economysim import game
from economysim.model import (
    CAMP, ENGAGE, NOWHERE, REST, ROTATE, Action, Config, Cost, Objective, Ramp,
    available_objectives, camp_yield, legal_actions, start, step,
)
from economysim.players import ARCHETYPES, play, solve

ONE = (Objective("Only", difficulty=5, time=2, growth=1),)


def at(cfg, pos, **kw):
    return start(cfg)._replace(pos=pos, **kw)


class Curves(unittest.TestCase):
    def test_linear_ramp(self):
        self.assertEqual(Ramp(rate=3)(2), 6)

    def test_table_ramp_repeats_last_value(self):
        r = Ramp(kind="table", table=(0, 2, 5))
        self.assertEqual([r(k) for k in range(5)], [0, 2, 5, 5, 5])

    def test_cost_has_floor(self):
        self.assertEqual(Cost(floor=1)(5, 10), 1)
        self.assertEqual(Cost()(9, 4), 5)


class Encounters(unittest.TestCase):
    def test_objective_grants_growth_and_advancement(self):
        cfg = Config(objectives=ONE + ONE)
        n = step(cfg, at(cfg, 0), Action(ENGAGE)).state
        self.assertEqual((n.growth, n.done, n.pos), (1, 1, NOWHERE))
        self.assertEqual(n.attrition, cfg.attrition - 5)
        self.assertEqual(n.time, cfg.time - 2)

    def test_challenge_ramps_with_advancement(self):
        cfg = Config(objectives=ONE + ONE, ramp=Ramp(rate=3))
        s = at(cfg, 1, done=1)
        self.assertEqual(step(cfg, s, Action(ENGAGE)).cost, 5 + 3)

    def test_rest_restores_up_to_cap_and_only_at_rest_site(self):
        cfg = Config()
        n = step(cfg, at(cfg, REST, attrition=10), Action(ENGAGE)).state
        self.assertEqual(n.attrition, cfg.attrition)
        self.assertNotIn(Action(ENGAGE), legal_actions(cfg, at(cfg, NOWHERE, attrition=3)))

    def test_no_rest_sites(self):
        cfg = Config(rest_sites=0)
        self.assertNotIn(Action(ROTATE, REST), legal_actions(cfg, start(cfg)))

    def test_rotation_moves_and_costs(self):
        cfg = Config()
        r = step(cfg, start(cfg), Action(ROTATE, CAMP))
        self.assertEqual(r.state.pos, CAMP)
        self.assertEqual((r.time, r.cost), (cfg.rotation_time, cfg.rotation_attrition))

    def test_running_out_of_time_loses(self):
        cfg = Config(objectives=ONE)
        n = step(cfg, at(cfg, 0, time=1), Action(ENGAGE)).state
        self.assertEqual((n.status, n.end), ("lost", "time"))

    def test_finishing_last_objective_wins(self):
        cfg = Config(objectives=ONE)
        self.assertEqual(step(cfg, at(cfg, 0), Action(ENGAGE)).state.status, "won")


class FullAttrition(unittest.TestCase):
    def failing(self, **kw):
        cfg = Config(objectives=ONE + ONE, **kw)
        return cfg, at(cfg, 0, attrition=5)  # cost 5 drains the pool to 0

    def test_cost_equal_to_pool_fails(self):
        cfg, s = self.failing()
        self.assertTrue(step(cfg, s, Action(ENGAGE)).failed)

    def test_elimination_ends_session(self):
        cfg, s = self.failing(failure="elimination")
        n = step(cfg, s, Action(ENGAGE)).state
        self.assertEqual((n.status, n.end), ("lost", "eliminated"))

    def test_delay_costs_time_and_recovers(self):
        cfg, s = self.failing(failure="delay", delay_time=8, delay_recover=6)
        n = step(cfg, s, Action(ENGAGE)).state
        self.assertEqual(n.status, "active")
        self.assertEqual(n.time, cfg.time - 2 - 8)
        self.assertEqual((n.attrition, n.done, n.pos), (6, 0, 0))

    def test_delay_growth_loss(self):
        cfg, s = self.failing(failure="delay", delay_growth_loss=3)
        n = step(cfg, s._replace(growth=2, attrition=3), Action(ENGAGE)).state
        self.assertEqual(n.growth, 0)

    def test_delay_relocate(self):
        cfg, s = self.failing(failure="delay", delay_relocate=True)
        self.assertEqual(step(cfg, s, Action(ENGAGE)).state.pos, NOWHERE)

    def test_delay_without_retry_loses_objective(self):
        cfg, s = self.failing(failure="delay", delay_retry=False)
        self.assertEqual(step(cfg, s, Action(ENGAGE)).state.end, "objective lost")

    def test_delay_into_zero_time_loses(self):
        cfg, s = self.failing(failure="delay", delay_time=100)
        self.assertEqual(step(cfg, s, Action(ENGAGE)).state.end, "time")


class Fundamentals(unittest.TestCase):
    def test_fixed_sequence_offers_next_only(self):
        cfg = Config(sequence="fixed")
        self.assertEqual(available_objectives(cfg, start(cfg)), [0])

    def test_free_sequence_offers_all_remaining(self):
        cfg = Config(sequence="free")
        s = start(cfg)._replace(done=0b0101)
        self.assertEqual(available_objectives(cfg, s), [1, 3])

    def test_growth_modes(self):
        s = start(Config())
        for mode, yields in (
            ("renewable", [4, 4, 4, 4, 4]),
            ("finite", [4, 4, 4, 0, 0]),
            ("diminishing", [4, 3, 2, 1, 0]),
        ):
            cfg = Config(growth=mode, camp_yield=4, camp_count=3, camp_decay=1)
            self.assertEqual([camp_yield(cfg, s._replace(camps=n)) for n in range(5)], yields, mode)

    def test_exhausted_camps_not_offered(self):
        cfg = Config(growth="finite", camp_count=1)
        self.assertNotIn(Action(ROTATE, CAMP), legal_actions(cfg, start(cfg)._replace(camps=1)))


class Players(unittest.TestCase):
    def test_optimal_wins_every_default_configuration(self):
        for f in ("elimination", "delay"):
            for q in ("fixed", "free"):
                for g in ("renewable", "finite", "diminishing"):
                    cfg = Config(failure=f, sequence=q, growth=g)
                    self.assertEqual(solve(cfg).final.status, "won", cfg.fundamentals())

    def test_optimal_is_at_least_as_good_as_archetypes(self):
        cfg = Config(sequence="free", growth="finite")
        best = solve(cfg).final
        for a in ARCHETYPES.values():
            s = play(cfg, a).final
            self.assertGreaterEqual((best.status == "won", best.time), (s.status == "won", s.time))

    def test_archetypes_only_take_legal_actions(self):
        cfg = Config(failure="delay")
        for a in ARCHETYPES.values():
            play(cfg, a)  # step() raises on an illegal action


class ConfigLoading(unittest.TestCase):
    def test_from_dict(self):
        cfg = Config.from_dict({
            "failure": "delay",
            "objectives": [{"name": "A", "difficulty": 3, "time": 2, "growth": 1}],
            "ramp": {"kind": "table", "table": [0, 4]},
            "cost": {"floor": 2},
        })
        self.assertEqual(cfg.objectives[0].name, "A")
        self.assertEqual(cfg.ramp(1), 4)
        self.assertEqual(cfg.cost(1, 0), 2)

    def test_round_trip(self):
        self.assertEqual(Config.from_dict(Config().to_dict()), Config())

    def test_rejects_unknown_keys_and_modes(self):
        with self.assertRaises(ValueError):
            Config.from_dict({"tiem": 5})
        with self.assertRaises(ValueError):
            Config(growth="infinite")


class Game(unittest.TestCase):
    def test_scripted_session(self):
        cfg = Config(objectives=ONE)
        inputs = iter(["h", "s", "9", "1", "1"])
        out = []
        s = game.run(cfg, input=lambda _: next(inputs), print=lambda *a: out.append(' '.join(map(str, a))))
        self.assertEqual(s.status, "won")
        self.assertTrue(any("WON" in line for line in out))


if __name__ == "__main__":
    unittest.main()
