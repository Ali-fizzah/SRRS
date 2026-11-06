# Performance results (tasks P7-T1, P7-T2)

Measured with `make load N=50000` on a developer's Windows machine with Docker Desktop. Times will differ on other machines, so run it again on the machine used for the final demonstration.

## Result

**L01 passes.** 50,000 contract lines, with every allocation checked against the generator's independent answers.

| Stage | Seconds | Target |
|---|---:|---|
| Upload and validation | 126 | |
| Recognition (the engine) | 55 | under 60 |
| Journal generation | 75 | |
| **Total** | **256** | **under 300** |
| Approve and post | 2 | not counted |
| Close checklist | 1 | not counted |

The dataset: 17,881 contracts, 44,727 obligations, 19,278 invoices, 313,398 schedule lines, 137,200 journal lines. No rows were rejected, nothing was skipped, and debits equal credits.

The margins are small: 5 seconds on the engine and 44 seconds on the total. A slower machine may miss them.

## What changed

| Run | Recognition | Journals | Total |
|---|---:|---:|---:|
| Before, 5,000 lines | 57 s | 22 s | 87 s (about 10 times that at 50,000) |
| After `COPY`, 50,000 lines | 67 s | 74 s | 270 s |
| After PostgreSQL settings and real chunking | 61 s | 76 s | 258 s |
| After reading only the columns needed | **55 s** | 75 s | **256 s** |

1. **`COPY` for obligations, schedules, schedule lines, journal entries and journal lines** (`app/db/bulk.py`).
2. **Planner statistics refreshed after bulk writes.** Without this, posting could take over an hour (see [validation-log.md](validation-log.md)).
3. **Recognition commits every 2,000 contract versions** (plan §10). If a run fails, finished contracts stay saved, each one complete, and running it again carries on.
4. **Recognition no longer loads uploaded source rows**, which it never reads.
5. **PostgreSQL settings** in `docker-compose.yml`: more memory and fewer checkpoints during bulk loads.

### Different from the plan: no NumPy

P7-T1 says to vectorise schedule generation with NumPy. Profiling showed the maths was a small share of the time and about 80-90% went on database writes, so NumPy would not have met the target. It would also have put fixed-size integers where the engine now has exact Python integers (D1). The acceptance figure, under 60 seconds, is met without it.

"Engine" here means the whole recognition stage, including its database writes, which is the stricter reading.

## Pages at 50,000 lines

Time for one page of results, on the machine above.

| Page | Seconds |
|---|---:|
| Contract list, including filter and sort | 0.1 |
| One contract: schedule, billing, source rows, journal lines | under 0.1 |
| Journal batch, first page and page 500 | 0.4 to 0.8 |
| Revenue schedule report | 0.2 to 1.0 |
| Deferred rollforward, by month | 1.0 |
| Deferred rollforward, by contract (slowest) | 2.3 |
| Trend, GL summary, MRR / ARR, close status | 1.0 to 1.4 |
| Journal register | 1.0 to 1.7 |
| Close checklist | 1.4 |
| Revenue schedule CSV, all 313,398 rows | 44 |

## Index review

No new index was needed. `EXPLAIN ANALYZE` on the queries the close and journals depend on shows them using `ix_schedule_lines_status_service_period` and `ix_schedule_lines_posting_period`, in milliseconds.

Some foreign-key indexes went unused in this run, such as `ix_journal_lines_account_id`. They stay, because plan §6.2 requires an index on every foreign key.

## What this does not cover

- One month's load at full size. The replay of many months is tested on smaller datasets (`make stress`).
- Several users at once.
- Contract events at this size: the load uses the `bundles` profile. Event handling writes per contract, so a month with thousands of events would be slower.
