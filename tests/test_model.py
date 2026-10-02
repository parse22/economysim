import unittest

from economysim import game
from economysim.model import (
    CAMP, ENGAGE, NOWHERE, REST, ROTATE, Action, Config, Cost, Objective, Ramp, State, TimeScaling,
    available_objectives, camp_yield, legal_actions, start, step,
)
from economysim.players import ARCHETYPES, play, score, solve

ONE = (Objective("Only", difficulty=5, time=2, growth=1),)


def at(cfg, pos, **kw):
    return start(cfg)._replace(pos=pos, **kw)


class Curves(unittest.TestCase):
    def test_linear_ramp(self):
        self.assertEqual(Ramp(rate=3)(2), 6)

    def test_table_ramp_repeats_last_value(self):
        r = Ramp(kind="table", table=(0, 2, 5))
        self.assertEqual([r(k) for k in range(5)], [0, 2, 5, 5, 5])

    def test_none_ramp_is_zero(self):
        self.assertEqual(Ramp(kind="none", rate=5)(3), 0)

    def test_cost_curve_explodes_when_underleveled(self):
        c = Cost(kind="curve", base=4, under=1.5, over=0.5, floor=1)
        self.assertEqual([c(g, 0) for g in (0, 1, 2, 4)], [4, 6, 9, 20])  # 4 * 1.5^n

    def test_cost_curve_diminishing_returns_when_overleveled(self):
        c = Cost(kind="curve", base=5, under=1.5, over=0.5, floor=1)
        self.assertEqual([c(0, g) for g in (0, 1, 2, 3, 10)], [5, 3, 2, 2, 1])  # 1 + 4 * 0.5^n

    def test_time_scaling(self):
        t = TimeScaling(kind="curve", under=1.5, over=0.5, fastest=0.5)
        self.assertEqual(TimeScaling()(4, 10, 0), 4)            # none
        self.assertEqual(t(4, 2, 0), 9)                          # 4 * 2.25
        self.assertEqual([t(4, 0, g) for g in (1, 2, 20)], [3, 2, 2])  # 4 * (0.5 + 0.5 * 0.5^n)
        self.assertEqual(t(1, 0, 20), 1)                         # never below 1

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

    def test_camp_challenge_fixed_by_default(self):
        cfg = Config(camp_challenge=5)
        r = step(cfg, at(cfg, CAMP, done=0b11), Action(ENGAGE))
        self.assertEqual(r.cost, 5)

    def test_time_scaling_applies_separately_to_camps_and_objectives(self):
        cfg = Config(objectives=ONE + ONE, camp_time=3,
                     objective_time_scaling=TimeScaling(kind="curve", under=2.0),
                     camp_time_scaling=TimeScaling(kind="none"))
        self.assertEqual(step(cfg, at(cfg, 0), Action(ENGAGE)).time, 2 * 2 ** 5)  # gap 5
        self.assertEqual(step(cfg, at(cfg, CAMP), Action(ENGAGE)).time, 3)

    def test_camp_ramp_scales_with_advancement_separately(self):
        cfg = Config(camp_challenge=5, ramp=Ramp(rate=3), camp_ramp=Ramp(kind="linear", rate=1))
        r = step(cfg, at(cfg, CAMP, done=0b11), Action(ENGAGE))
        self.assertEqual(r.cost, 5 + 2)

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

    def test_failure_is_counted(self):
        cfg, s = self.failing(failure="delay")
        self.assertEqual(step(cfg, s, Action(ENGAGE)).state.failures, 1)

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


class LossScoring(unittest.TestCase):
    def test_win_beats_any_loss(self):
        won = State(time=0, attrition=1, status="won", done=1)
        lost = State(time=50, attrition=12, growth=99, status="lost", end="time", done=7)
        self.assertGreater(score(won), score(lost))

    def test_losses_ignore_leftover_time_and_prefer_time_over_elimination(self):
        out_of_time = State(time=0, attrition=1, growth=5, done=3, status="lost", end="time")
        eliminated = State(time=20, attrition=0, growth=5, done=3, status="lost", end="eliminated")
        self.assertGreater(score(out_of_time), score(eliminated))

    def test_losses_rank_advancement_first(self):
        more = State(time=0, attrition=0, growth=0, done=7, status="lost", end="eliminated")
        less = State(time=0, attrition=5, growth=9, done=3, status="lost", end="time")
        self.assertGreater(score(more), score(less))


class Rusher(unittest.TestCase):
    def test_attacks_unbeatable_objective_under_elimination(self):
        run = play(Config(failure="elimination"), ARCHETYPES["rusher"])
        self.assertEqual(run.final.end, "eliminated")
        self.assertEqual(run.count(Config(), CAMP), 0)

    def test_camps_once_per_failure_under_delay(self):
        cfg = Config(failure="delay")
        run = play(cfg, ARCHETYPES["rusher"])
        self.assertGreater(run.failures, 0)
        self.assertLessEqual(run.final.camps, run.final.failures)
        self.assertGreater(run.final.camps, 0)

    def test_never_camps_without_failing(self):
        cfg = Config(objectives=ONE, failure="delay")
        run = play(cfg, ARCHETYPES["rusher"])
        self.assertEqual((run.final.status, run.final.camps), ("won", 0))

    def test_no_rest_loop_when_resting_cannot_help(self):
        # The Fortress costs more than a full pool. The old rule travelled to it,
        # turned back to rest, and repeated until time ran out.
        for f in ("delay", "elimination"):
            run = play(Config(failure=f), ARCHETYPES["rusher"])
            kinds = [a.kind for a in run.actions]
            self.assertNotIn((ROTATE, ROTATE), list(zip(kinds, kinds[1:])), f)


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
        with self.assertRaises(ValueError):
            Config(camp_ramp=Ramp(kind="steep"))
        with self.assertRaises(ValueError):
            Config(cost=Cost(kind="curve", over=1.5))
        with self.assertRaises(ValueError):
            Config(camp_time_scaling=TimeScaling(kind="curve", fastest=0))


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
