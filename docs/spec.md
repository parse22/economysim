# Encounter Economy Fundamentals — Specification

An abstract model of a roguelike (Nightreign-style) session economy. Real time,
space and combat are abstracted away. The purpose is to make it easy to test
configurations of the fundamental design questions: the critical decision points
that shape the player's experience of the economy and the design intent.

The model has two tiers:

- **Fundamentals**: categorical switches compared against each other.
- **Parameters**: numeric values and variants tuned within a chosen set of
  fundamentals.

## Foundational assumptions

- The session fails when Time reaches 0.
- Challenge rises only with Advancement.
- All objectives are required.

## Resources

| Resource    | Start | Meaning                                                         |
|-------------|-------|-----------------------------------------------------------------|
| Time        | T     | Session clock. Reaching 0 means session failure.                |
| Attrition   | A     | Pool that drains to 0. Reaching 0 is **full attrition**.        |
| Growth      | 0     | Player power to contest challenge. Lowers encounter attrition.  |
| Advancement | 0     | Objectives completed. Reaching N means session success.         |

Challenge is derived, not stored: an objective's challenge is its base
difficulty plus a ramp driven by Advancement.

## Encounters

| Encounter   | Time    | Attrition                   | Growth  | Advancement |
|-------------|---------|-----------------------------|---------|-------------|
| Camp        | −t_camp | −cost(C_camp + camp_ramp(k), G) | +yield |           |
| Objective i | −t_i    | −cost(d_i + ramp(k), G)     | +g_i    | +1          |
| Rest        | −t_rest | +restore (capped at A)      |         |             |
| Rotation    | −t_rot  | −a_rot                      |         |             |

- `G` is current Growth; `k` is current Advancement.
- `cost(C, G)` is the attrition an encounter of challenge `C` drains at
  Growth `G`. It falls as Growth rises relative to challenge.
- `ramp(k)` is the challenge added to objectives at Advancement `k`.
- `camp_ramp(k)` is the challenge added to camps at Advancement `k`. It is
  separate from the objective ramp and is off (`none`) by default, so camps
  keep a fixed challenge unless it is set.
- Both curves are configuration parameters for sim tuning (see Curves).
- Objectives are heterogeneous (`d_i`, `t_i`, `g_i`). This is what makes
  sequence meaningful: under free sequence, the player chooses which objective
  to take while the ramp is low.
- Rotation is movement on the map from one location to another. Its attrition
  cost is fixed; it is not contested.

## Time and space

The simulation is turn based, with time on a cost model. Time and position are
abstracted to discrete units:

- A **turn** is one decision: take the encounter here, or rotate elsewhere.
- **Time** is a budget, not a turn counter. Each encounter spends its own
  integer time cost, so turns differ in how much time they consume.
- **Position** is a set of discrete locations. Each location holds one
  encounter: a camp, an objective or a rest site.
- An encounter can only be taken at the player's current location. Moving to
  another location is a Rotation.
- Camps and objectives are consumed when completed. Rest sites are reusable.
- Rest is only available at rest sites. The number of rest sites is a
  parameter.
- Rotation cost is uniform between any two locations for now.

## Full attrition

Full attrition occurs when an encounter's attrition cost would drain the pool
to 0 (cost ≥ remaining attrition). This applies to every encounter that costs
attrition, Rotation included. The encounter **fails**: its time is still
spent, and it grants no Growth or Advancement (a failed Rotation does not
move the player). What happens next is fundamental question 1.

An encounter whose time cost exceeds the remaining Time ends the session
(time failure) without resolving.

## Fundamental questions

### 1. Does full attrition lead to delay or elimination?

- **Elimination**: the session ends in failure.
- **Delay**: the session continues after a penalty.

| Delay variant | Default   | Meaning                                                        |
|---------------|-----------|----------------------------------------------------------------|
| `t_delay`     | —         | Time lost. If Time reaches 0, the session fails.               |
| `A_recover`   | —         | Attrition pool after recovering.                               |
| `g_loss`      | 0         | Growth lost. 0 = time-only setback; > 0 = Nightreign-style.    |
| `retry`       | retryable | Whether the failed encounter remains available or is consumed. A consumed objective ends the session, since all objectives are required. |
| `relocate`    | false     | Whether recovering forces a Rotation before the next encounter.|

Growth loss is a variant of delay rather than a separate fundamental.

### 2. Is objective sequence fixed or free?

- **Fixed**: objectives must be completed in a set order.
- **Free**: the player chooses the order.

Optional or bypassable objectives are out of scope: they add externalities and
simulation complexity without being fundamental at this stage.

### 3. Is growth renewable, finite or diminishing?

Supply describes the map's total growth, not its accessibility. Rotation is
still required to reach growth in every mode.

- **Renewable**: unlimited camps; every camp yields `yield`.
- **Finite**: a fixed number of camps per session, each yielding `yield`.
- **Diminishing**: each successive camp yields less than the previous one.

### Configuration space

2 (failure) × 2 (sequence) × 3 (growth) = **12 fundamental configurations**.

## Parameters

| Group       | Parameters                                                    |
|-------------|---------------------------------------------------------------|
| Session     | T, A, N                                                       |
| Objectives  | d_i, t_i, g_i for each objective                              |
| Camp        | t_camp, C_camp, yield, camp count (finite), decay (diminishing), camp_ramp |
| Rest        | t_rest, restore, number of rest sites                         |
| Rotation    | t_rot, a_rot                                                  |
| Curves      | cost() and ramp(), selected and tuned per configuration       |
| Delay       | t_delay, A_recover, g_loss, retry, relocate                   |

## Curves

`cost()` and `ramp()` are configurable rather than fixed, so their shape can
be tuned per configuration. Each is chosen from a small set of named forms
with numeric parameters, for example:

- `ramp(k)` and `camp_ramp(k)`: none (always 0), linear (`rate × k`), or an
  explicit per-step table.
- `cost(C, G)`: linear difference with a floor (`max(c_min, C − G)`).

Further forms can be added as tuning needs them.

## Out of scope for now

- Rest anywhere (a possible later sim option).
- Optional or bypassable objectives.
- Non-uniform distances between locations.
- Variance in encounter costs.

## Player models

Each configuration is evaluated by two kinds of simulated player, and can
also be played by hand:

- **Optimal**: exhaustive search over every sequence of decisions, with
  perfect information. Shows the best outcome a configuration permits and the
  route to it. A win ranks above any loss; wins rank by time left, then
  attrition left, then growth. Leftover time and attrition mean nothing after
  a loss, so losses rank by advancement, then growth, then running out of
  time over elimination.
- **Archetypes**: rule-based players representing play styles.
  - Rusher: always heads for the next objective. Camps only after a failure:
    one camp per failure, then back to the objective.
  - Balanced: camps until the next objective costs at most half the pool;
    rests below a quarter.
  - Cautious: camps until the next objective costs at most a quarter of the
    pool; rests below half.

  Shared rules for all archetypes:
  - Under free sequence, the next objective is the one with the lowest
    current challenge.
  - Before an encounter it cannot afford, or one that would leave too little
    attrition to rotate back to a rest site, an archetype rests, but only if
    resting would let the encounter succeed. If even a full pool cannot pay
    for it, the archetype attacks anyway and accepts the failure.
  - When camps have run out, an archetype that wants or owes a camp heads for
    the objective instead.
- **Interactive**: a human picks each action.

The gap between optimal and archetype results indicates how much a
configuration rewards skill.

Encounter costs are deterministic for now. Variance is a possible later
option.

## Notation

Attrition is written as a pool that drains to zero. The notation may be
revisited in a later iteration.
