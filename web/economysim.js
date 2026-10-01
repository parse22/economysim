/* Encounter economy model: a JavaScript port of economysim/model.py and
 * economysim/players.py. tests/test_web_parity.py checks that both produce
 * identical runs, so change them together. Rules: docs/spec.md. */
(function (root) {
  "use strict";

  const NOWHERE = -1, CAMP = -2, REST = -3;
  const ROTATE = "rotate", ENGAGE = "engage";
  const FAILURE_MODES = ["elimination", "delay"];
  const SEQUENCE_MODES = ["fixed", "free"];
  const GROWTH_MODES = ["renewable", "finite", "diminishing"];

  const DEFAULT_CONFIG = {
    failure: "elimination", sequence: "fixed", growth: "renewable",
    time: 75, attrition: 12,
    objectives: [
      { name: "Outpost", difficulty: 5, time: 3, growth: 1 },
      { name: "Watchtower", difficulty: 7, time: 3, growth: 1 },
      { name: "Fortress", difficulty: 9, time: 4, growth: 1 },
      { name: "Citadel", difficulty: 11, time: 5, growth: 0 },
    ],
    camp_time: 3, camp_challenge: 5, camp_yield: 4, camp_count: 3, camp_decay: 1,
    rest_time: 3, rest_restore: 6, rest_sites: 1,
    rotation_time: 2, rotation_attrition: 1,
    ramp: { kind: "linear", rate: 3, table: [] },
    cost: { kind: "linear", floor: 1, scale: 1.0 },
    delay_time: 8, delay_recover: 6, delay_growth_loss: 0,
    delay_retry: true, delay_relocate: false,
  };

  function defaultConfig() { return JSON.parse(JSON.stringify(DEFAULT_CONFIG)); }

  function validate(cfg) {
    const check = (name, allowed) => {
      if (!allowed.includes(cfg[name])) throw new Error(`${name} must be one of ${allowed.join(", ")}`);
    };
    check("failure", FAILURE_MODES); check("sequence", SEQUENCE_MODES); check("growth", GROWTH_MODES);
    if (!cfg.objectives.length) throw new Error("at least one objective is required");
    const times = [cfg.camp_time, cfg.rest_time, cfg.rotation_time, ...cfg.objectives.map(o => o.time)];
    if (Math.min(...times) < 1) throw new Error("every encounter must cost at least 1 time");
    if (cfg.delay_recover < 1) throw new Error("delay_recover must be at least 1");
    if (!["linear", "table"].includes(cfg.ramp.kind)) throw new Error("ramp kind must be linear or table");
    if (cfg.cost.kind !== "linear") throw new Error("cost kind must be linear");
    return cfg;
  }

  function withFundamentals(cfg, failure, sequence, growth) {
    return Object.assign({}, cfg, {
      failure: failure || cfg.failure, sequence: sequence || cfg.sequence, growth: growth || cfg.growth,
    });
  }

  const fundamentals = cfg => `${cfg.failure}/${cfg.sequence}/${cfg.growth}`;

  // Python's round(): halves go to the even neighbour.
  function pyRound(x) {
    const f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }

  function ramp(cfg, k) {
    const r = cfg.ramp;
    if (r.kind === "linear") return r.rate * k;
    if (r.kind === "table") return r.table.length ? r.table[Math.min(k, r.table.length - 1)] : 0;
    throw new Error(`unknown ramp kind ${r.kind}`);
  }

  function cost(cfg, challenge, growth) {
    return Math.max(cfg.cost.floor, pyRound(cfg.cost.scale * (challenge - growth)));
  }

  function start(cfg) {
    return { time: cfg.time, attrition: cfg.attrition, growth: 0, done: 0, pos: NOWHERE, camps: 0, failures: 0, status: "active", end: "" };
  }

  function advancement(s) { let n = 0, d = s.done; while (d) { n += d & 1; d >>= 1; } return n; }
  const allDone = cfg => (1 << cfg.objectives.length) - 1;
  const challenge = (cfg, s, i) => cfg.objectives[i].difficulty + ramp(cfg, advancement(s));

  function campYield(cfg, s) {
    if (cfg.growth === "finite") return s.camps < cfg.camp_count ? cfg.camp_yield : 0;
    if (cfg.growth === "diminishing") return Math.max(0, cfg.camp_yield - cfg.camp_decay * s.camps);
    return cfg.camp_yield;
  }

  function availableObjectives(cfg, s) {
    const remaining = [];
    for (let i = 0; i < cfg.objectives.length; i++) if (!((s.done >> i) & 1)) remaining.push(i);
    return cfg.sequence === "free" ? remaining : remaining.slice(0, 1);
  }

  function positionName(cfg, pos) {
    if (pos === NOWHERE) return "on the road";
    if (pos === CAMP) return "Camp";
    if (pos === REST) return "Rest site";
    return cfg.objectives[pos].name;
  }

  function legalActions(cfg, s) {
    if (s.status !== "active") return [];
    const actions = [];
    if (s.pos === CAMP || s.pos >= 0 || (s.pos === REST && s.attrition < cfg.attrition))
      actions.push({ kind: ENGAGE, target: null });
    for (const i of availableObjectives(cfg, s)) if (s.pos !== i) actions.push({ kind: ROTATE, target: i });
    if (s.pos !== CAMP && campYield(cfg, s) > 0) actions.push({ kind: ROTATE, target: CAMP });
    if (s.pos !== REST && cfg.rest_sites > 0) actions.push({ kind: ROTATE, target: REST });
    return actions;
  }

  function actionCosts(cfg, s, a) {
    if (a.kind === ROTATE) return [cfg.rotation_time, cfg.rotation_attrition];
    if (s.pos === CAMP) return [cfg.camp_time, cost(cfg, cfg.camp_challenge, s.growth)];
    if (s.pos === REST) return [cfg.rest_time, 0];
    return [cfg.objectives[s.pos].time, cost(cfg, challenge(cfg, s, s.pos), s.growth)];
  }

  function describe(cfg, s, a) {
    if (a.kind === ROTATE) {
      if (a.target >= 0) return `Rotate to ${cfg.objectives[a.target].name} (challenge ${challenge(cfg, s, a.target)})`;
      return `Rotate to ${positionName(cfg, a.target)}`;
    }
    if (s.pos === CAMP) return `Camp (+${campYield(cfg, s)} growth)`;
    if (s.pos === REST) return `Rest (+${Math.min(cfg.rest_restore, cfg.attrition - s.attrition)} attrition)`;
    const obj = cfg.objectives[s.pos];
    return `Take ${obj.name} (+${obj.growth} growth, +1 advancement)`;
  }

  const sameAction = (a, b) => a.kind === b.kind && a.target === b.target;
  const end = (s, status, why) => Object.assign({}, s, { status, end: why });

  function step(cfg, s, a, check = true) {
    if (check && !legalActions(cfg, s).some(b => sameAction(a, b))) throw new Error("illegal action");
    const [t, c] = actionCosts(cfg, s, a);
    const label = describe(cfg, s, a);
    const time = s.time - t;
    if (time < 0) {
      return { state: end(Object.assign({}, s, { time: 0 }), "lost", "time"), time: t, cost: c, failed: false,
               message: `${label}: ran out of time` };
    }
    if (c >= s.attrition) return fullAttrition(cfg, Object.assign({}, s, { time }), a, t, c, label);

    let n = Object.assign({}, s, { time, attrition: s.attrition - c });
    if (a.kind === ROTATE) n.pos = a.target;
    else if (s.pos === CAMP) Object.assign(n, { growth: n.growth + campYield(cfg, s), camps: s.camps + 1, pos: NOWHERE });
    else if (s.pos === REST) n.attrition = Math.min(cfg.attrition, s.attrition + cfg.rest_restore);
    else {
      const obj = cfg.objectives[s.pos];
      Object.assign(n, { growth: n.growth + obj.growth, done: s.done | (1 << s.pos), pos: NOWHERE });
    }
    if (n.done === allDone(cfg)) n = end(n, "won", "all objectives complete");
    else if (n.time === 0) n = end(n, "lost", "time");
    return { state: n, time: t, cost: c, failed: false, message: label };
  }

  function fullAttrition(cfg, s, a, t, c, label) {
    let msg = `${label}: FAILED, full attrition`;
    const result = (state, m) => ({ state, time: t, cost: c, failed: true, message: m });
    s = Object.assign({}, s, { failures: s.failures + 1 });
    if (cfg.failure === "elimination")
      return result(end(Object.assign({}, s, { attrition: 0 }), "lost", "eliminated"), msg + ", eliminated");

    const engaged = a.kind === ENGAGE;
    if (engaged && s.pos >= 0 && !cfg.delay_retry)
      return result(end(Object.assign({}, s, { attrition: 0 }), "lost", "objective lost"), msg + ", objective lost");

    let n = Object.assign({}, s, {
      time: Math.max(0, s.time - cfg.delay_time),
      attrition: Math.min(cfg.attrition, cfg.delay_recover),
      growth: Math.max(0, s.growth - cfg.delay_growth_loss),
    });
    if (engaged && s.pos === CAMP && !cfg.delay_retry) Object.assign(n, { camps: n.camps + 1, pos: NOWHERE });
    if (cfg.delay_relocate) n.pos = NOWHERE;
    msg += `, delayed ${cfg.delay_time} time`;
    if (cfg.delay_growth_loss) msg += `, lost ${cfg.delay_growth_loss} growth`;
    if (n.time === 0) n = end(n, "lost", "time");
    return result(n, msg);
  }

  // ---- Players ----

  function play(cfg, decide) {
    let s = start(cfg);
    const steps = [], actions = [];
    while (s.status === "active") {
      const a = decide(cfg, s);
      const st = step(cfg, s, a);
      steps.push(st); actions.push(a);
      s = st.state;
    }
    return { final: s, steps, actions };
  }

  function countEngaged(cfg, run, kind) {
    let n = 0, s = start(cfg);
    run.actions.forEach((a, i) => {
      if (a.kind === ENGAGE && s.pos === kind && !run.steps[i].failed) n++;
      s = run.steps[i].state;
    });
    return n;
  }

  const failures = run => run.steps.filter(s => s.failed).length;

  // A win ranks above any loss, then by leftover time, attrition and growth.
  // Losses rank by advancement, then growth, then running out of time over elimination.
  const score = s => s.status === "won"
    ? [1, advancement(s), s.time, s.attrition, s.growth]
    : [0, advancement(s), s.growth, s.end === "time" ? 1 : 0, 0];
  function better(a, b) {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] > b[i];
    return false;
  }

  const MAX_STATES = 4000000;

  function solve(cfg) {
    const memo = new Map();
    const key = s => `${s.time},${s.attrition},${s.growth},${s.done},${s.pos},${cfg.growth === "renewable" ? 0 : s.camps},${s.status},${s.end}`;
    function best(s) {
      const k = key(s);
      const hit = memo.get(k);
      if (hit) return hit;
      const actions = legalActions(cfg, s);
      let result;
      if (!actions.length) result = [score(s), null];
      else {
        for (const a of actions) {
          const sc = best(step(cfg, s, a, false).state)[0];
          if (!result || better(sc, result[0])) result = [sc, a];
        }
      }
      if (memo.size >= MAX_STATES) throw new Error("search too large: reduce time budget or objectives");
      memo.set(k, result);
      return result;
    }
    return play(cfg, (cfg, s) => best(s)[1]);
  }

  function archetype(name, growUntil, restBelow, campAfterFailure, summary) {
    const decide = (cfg, s) => {
      const options = availableObjectives(cfg, s);
      let target = options[0];
      for (const i of options) if (challenge(cfg, s, i) < challenge(cfg, s, target)) target = i;
      let c = cost(cfg, challenge(cfg, s, target), s.growth);

      const canRest = cfg.rest_sites > 0 && s.attrition < cfg.attrition;
      if (canRest && s.attrition < restBelow * cfg.attrition) return toward(s, REST);

      if (campYield(cfg, s) > 0) {
        const owed = campAfterFailure && s.failures > s.camps;
        const wants = growUntil !== null && c > growUntil * cfg.attrition;
        if (owed || wants) { target = CAMP; c = cost(cfg, cfg.camp_challenge, s.growth); }
      }

      if (canRest) {
        // From a rest site at full attrition: rotate, then the encounter.
        const afterRest = cfg.attrition - cfg.rotation_attrition - c;
        if (afterRest > 0) {
          let need = c + (s.pos === target ? 0 : cfg.rotation_attrition);
          if (afterRest > cfg.rotation_attrition) need += cfg.rotation_attrition; // keep enough to get back
          if (s.attrition <= need) return toward(s, REST);
        }
      }
      return toward(s, target);
    };
    decide.archetype = name; decide.summary = summary;
    return decide;
  }

  const toward = (s, target) => s.pos === target ? { kind: ENGAGE, target: null } : { kind: ROTATE, target };

  const ARCHETYPES = {
    rusher: archetype("rusher", null, 0.0, true, "always attacks; camps once after each failure"),
    balanced: archetype("balanced", 0.5, 0.25, false, "camps until objectives cost half the pool"),
    cautious: archetype("cautious", 0.25, 0.5, false, "camps until objectives are cheap; rests below half"),
  };

  const api = {
    NOWHERE, CAMP, REST, ROTATE, ENGAGE, FAILURE_MODES, SEQUENCE_MODES, GROWTH_MODES, ARCHETYPES,
    defaultConfig, validate, withFundamentals, fundamentals, ramp, cost, start, advancement, challenge,
    campYield, availableObjectives, positionName, legalActions, actionCosts, describe, step,
    play, solve, countEngaged, failures,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.EconomySim = api;
})(typeof self !== "undefined" ? self : this);
