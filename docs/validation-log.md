# Validation log (tasks P6-T2, P6-T3)

Findings from testing with realistic data. Accounting questions wait for M1, who owns these rules.

## Advisor review sessions (P6-T2)

**Not held yet.** M1 runs these sessions on realistic datasets and records the findings here, one row per session, and as issues.

| Date | Who attended | Dataset | Findings | Issues raised |
|---|---|---|---|---|
| | | | | |

To make a dataset for a session, run this in the project folder:

```powershell
docker compose run --rm api python ../tools/generate_dataset.py --lines 500 --seed 1 --profile full
```

The files appear in `benchmarks/generated/full_500_s1/inputs`, one folder per month, with the expected answers in `expected/`.

## How generated data is tested (P6-T3)

`tools/generate_dataset.py` writes contracts in the system's templates, and works out the expected results itself, with exact fractions and the plan's rules written out separately from the engine. A replay then pushes each dataset through upload, recognition, journals, approval, posting and close, month by month, and compares every amount.

The run order is the plan's: single contracts, then bundles, then events, then everything together. `make bench` runs one dataset of each; `make stress S=6 LINES=200` runs more.

These expected values are a second calculation written by the developers, so they catch bugs but are not M1's hand calculations (plan §11.4).

## Problems found by generated data

All three were invisible to the hand-written cases.

| # | Problem | Effect | Status |
|---|---|---|---|
| 1 | A point-in-time line delivered 50% + 50% on an odd amount rounds to more than the allocation, so §5.3's remainder is -0.01. The run mistook this for changing booked revenue and refused it. | Both deliveries ignored; revenue landed in the completion month, up to months late | Fixed. Regression test added. See question 1 |
| 2 | With stale database statistics, the update that marks schedule lines POSTED took over an hour on a 150-line dataset. | Posting could appear to hang after a large batch | Fixed: statistics refresh when a batch is saved (about 21 seconds for the same dataset). Phase 7 should measure this properly |
| 3 | Upload checked a credit note against the whole balance, but journals take documents by date then number (§5.6). A credit dated before a later invoice was accepted, then could not be booked. | That contract was never booked, and the month could never close | Fixed: upload now checks in journal order and gives E009. Regression tests added |

## Questions for M1

1. **Negative remainder.** Delivering 50% + 50% of 5.01 gives 2.51 + 2.51, then -0.01 in the completion month. That is §5.3 as written, and the total still equals the allocation. Is a small negative revenue line acceptable, or should the last delivery take the remainder instead?
2. **Documents for an old term after a renewal.** After a renewal, only the new term's lines can be referenced. A late invoice naming a line the new term dropped gets E004, and one naming a line both terms have attaches to the new term. The plan does not cover this. What should happen?
3. **A credit note already in the system cannot be removed.** Credits that come through upload are now safe. If one is ever loaded by another route, the contract stays unbooked and the month cannot close until someone corrects the data directly.
