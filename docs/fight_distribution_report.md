# Fight Engine Distribution Report (T3.1 / W12)

**Generated:** 2026-08-15 04:19:00
**DB:** `/home/z/my-project/cage_empire/data/cage_empire.db`
**Total resolved fights:** 3213

## Purpose

This report MEASURES the result_type distribution of resolved
fights in the world DB and compares it to real-world UFC
distributions. It is **MEASUREMENT ONLY** — it does NOT tune
any fight engine constants. Per the T3.1 brief, the user will
rebalance fighter attribute allocations separately later.

## Raw result_type distribution

| result_type           | count | percentage |
|-----------------------|-------|------------|
| doctor_stoppage       |   551 |    17.15% |
| dq                    |    31 |     0.96% |
| draw                  |    52 |     1.62% |
| ko_tko                |   805 |    25.05% |
| no_contest            |    62 |     1.93% |
| split_decision        |   175 |     5.45% |
| submission            |   622 |    19.36% |
| unanimous_decision    |   915 |    28.48% |
| TOTAL                 |  3213 |   100.00% |

## Composite categories (per the brief)

The brief specifies the comparison in composite categories:
KO%, sub%, decision% (UD+split), draw%, DQ%, doctor_stoppage%,
no_contest%.

| Category          | result_types                          | count | actual % | target % | gap (pp) |
|-------------------|---------------------------------------|-------|----------|----------|----------|
| KO/TKO            | ko_tko                                |   805 |   25.05% |   35.00% |   -9.95 |
| Submission        | submission                            |   622 |   19.36% |   20.00% |   -0.64 |
| Decision          | unanimous_decision+split_decision     |  1090 |   33.92% |   45.00% |  -11.08 |
| Draw              | draw                                  |    52 |    1.62% |    1.00% |   +0.62 |
| DQ                | dq                                    |    31 |    0.96% |    0.50% |   +0.46 |
| Doctor Stoppage   | doctor_stoppage                       |   551 |   17.15% |    1.00% |  +16.15 |
| No Contest        | no_contest                            |    62 |    1.93% |    0.50% |   +1.43 |

## Comparison to real-world UFC distributions

Real-world UFC distributions (approximate, per the brief):

- KO ~35% (knockouts + technical knockouts)
- Submission ~20% (tap-outs)
- Decision ~45% (unanimous + split decisions combined)
- Draw ~1%
- DQ ~0.5%
- Doctor Stoppage ~1%
- No Contest ~0.5%

## Gap analysis

The gap column (above) shows the difference between the actual
distribution and the target UFC distribution, in percentage
points (pp). A positive gap means the actual is HIGHER than
the target; a negative gap means the actual is LOWER.

Largest gaps (sorted by absolute gap):

- **Doctor Stoppage**: actual 17.15% vs target 1.00% → gap +16.15pp (HIGHER)
- **Decision**: actual 33.92% vs target 45.00% → gap -11.08pp (LOWER)
- **KO/TKO**: actual 25.05% vs target 35.00% → gap -9.95pp (LOWER)
- **No Contest**: actual 1.93% vs target 0.50% → gap +1.43pp (HIGHER)
- **Submission**: actual 19.36% vs target 20.00% → gap -0.64pp (LOWER)
- **Draw**: actual 1.62% vs target 1.00% → gap +0.62pp (HIGHER)
- **DQ**: actual 0.96% vs target 0.50% → gap +0.46pp (ON TARGET)

## Tuning guidance (for the user's separate fighter-attribute rebalance)

This script does NOT tune any fight engine constants. The gaps
above identify where the actual distribution diverges from the
target. Common fighter-attribute adjustments that affect each
category:

- **KO/TKO too high** → reduce average striking_power /
  increase average durability / reduce aggression (fewer
  wild exchanges).
- **KO/TKO too low** → increase average striking_power /
  decrease average durability / increase aggression.
- **Submission too high** → reduce average submission_skill /
  increase average submission_defense.
- **Submission too low** → increase average submission_skill /
  decrease average submission_defense.
- **Decision too high** → increase average striking_power /
  aggression (more finishes, fewer decisions).
- **Decision too low** → decrease average striking_power /
  increase average durability / cardio (fights go longer).

## Conclusion

This report is a SNAPSHOT of the current distribution. After
the user rebalances fighter attributes, re-run this script to
verify the distribution has shifted toward the target.
