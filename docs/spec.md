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
| Camp        | −t_camp | −cost(C_camp, G)            | +yield  |             |
| Objective i | −t_i    | −cost(d_i + ramp(k), G)     | +g_i    | +1          |
| Rest        | −t_rest | +restore (capped at A)      |         |             |
| Rotation    | −t_rot  | −a_rot                      |         |             |

- `G` is current Growth; `k` is current Advancement.
- `cost(C, G)` is the attrition an encounter of challenge `C` drains at
  Growth `G`. It falls as Growth rises relative to challenge.
- `ramp(k)` is the challenge added at Advancement `k`.
- Both curves are configuration parameters for sim tuning (see Curves).
- Objectives are heterogeneous (`d_i`, `t_i`, `g_i`). This is what makes
  sequence meaningful: under free sequence, the player chooses which objective
  to take while the ramp is low.
- Rotation is movement on the map from one location to another. Its attrition
  cost is fixed; it is not contested.

## Time and space

The simulation is turn based. Time and position are abstracted to discrete
units:

- **Time** is an integer count of turns. Every encounter costs a whole number
  of turns.
- **Position** is a set of discrete locations. Each location holds one
  encounter: a camp, an objective or a rest site.
- An encounter can only be taken at the player's current location. Moving to
  another location is a Rotation.
- Camps and objectives are consumed when completed. Rest sites are reusable.
- Rest is only available at rest sites. The number of rest sites is a
  parameter.
- Rotation cost is uniform between any two locations for now.

## Full attrition

Full attrition occurs when an encounter's attrition cost exceeds the remaining
pool. The encounter **fails**: its time is still spent, and it grants no
Growth or Advancement. What happens next is fundamental question 1.

## Fundamental questions

### 1. Does full attrition lead to delay or elimination?

- **Elimination**: the session ends in failure.
- **Delay**: the session continues after a penalty.

| Delay variant | Default   | Meaning                                                        |
|---------------|-----------|----------------------------------------------------------------|
| `t_delay`     | —         | Time lost. If Time reaches 0, the session fails.               |
| `A_recover`   | —         | Attrition pool after recovering.                               |
| `g_loss`      | 0         | Growth lost. 0 = time-only setback; > 0 = Nightreign-style.    |
| `retry`       | retryable | Whether the failed encounter remains available or is consumed. |
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
| Camp        | t_camp, C_camp, yield, camp count (finite), decay (diminishing) |
| Rest        | t_rest, restore, number of rest sites                         |
| Rotation    | t_rot, a_rot                                                  |
| Curves      | cost() and ramp(), selected and tuned per configuration       |
| Delay       | t_delay, A_recover, g_loss, retry, relocate                   |

## Curves

`cost()` and `ramp()` are configurable rather than fixed, so their shape can
be tuned per configuration. Each is chosen from a small set of named forms
with numeric parameters, for example:

- `ramp(k)`: linear (`rate × k`), or an explicit per-step table.
- `cost(C, G)`: linear difference with a floor (`max(c_min, C − G)`).

Further forms can be added as tuning needs them.

## Out of scope for now

- Rest anywhere (a possible later sim option).
- Optional or bypassable objectives.
- Non-uniform distances between locations.

## Not yet specified

- How player decisions are made when the simulation is run.

## Notation

Attrition is written as a pool that drains to zero. The notation may be
revisited in a later iteration.
