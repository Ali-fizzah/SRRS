# Evidence map for the thesis (task P8-T3)

For M1, writing the implementation and testing chapters. It shows where each claim's evidence lives, so the thesis can cite the repository. **Cite a tag, such as `v1.0.0`, not a branch**, so references stay valid. The figures below predate M1's sign-off: take final figures from the signed report.

## Implementation chapter

| Topic | Evidence |
|---|---|
| Requirements and decisions | `docs/DEVELOPMENT_PLAN.md`: §2 decisions, §5 accounting specification |
| Data model | `docs/erd.md`, `docs/release/schema.sql` |
| Exact money and rounding | `backend/app/engine/money.py`, `allocation.py`, `methods.py` |
| Engine with no database or clock | `backend/app/engine/`, enforced by `tests/unit/test_engine_purity.py` |
| Contract events | `backend/app/services/contract_events.py` |
| Journals and lifecycle | `backend/app/services/journals.py`, `engine/journal_rules.py` |
| Period close | `backend/app/services/period_close.py` |
| Immutability in the database | Migration `20261103_cd795a034367_immutability_triggers.py`, `tests/integration/test_triggers.py` |
| Traceability to the source file | `source_upload_id`, `source_row` and `source_payload` columns; the contract page's Source rows tab |
| Roles | `backend/app/auth/`, `tests/integration/test_role_matrix.py` |
| Bulk loading | `backend/app/db/bulk.py`, `docs/performance.md` |

## Testing chapter

| Claim | Evidence | Reproduce with |
|---|---|---|
| Outputs match the Excel workbooks within 0.01 | `benchmarks/cases/X01*`, `X02*`, from `benchmarks/source/` | `make bench` |
| Per-case variance | `docs/test-report/test-report.pdf` | `make report` |
| Hand-worked golden cases | `benchmarks/cases/`, each with `case.yaml` | `make bench` |
| Randomised data, answers calculated separately from the engine | `tools/generate_dataset.py` | `make stress` |
| The test harness itself fails on wrong values | `tests/benchmarks/test_runner_catches_errors.py` | `make bench` |
| Property tests on the arithmetic | `tests/unit/`, using Hypothesis | `make test` |
| 50,000-line performance target | `docs/performance.md` | `make load N=50000` |
| Security review | `docs/security-pass.md` | `make test` |
| Accessibility | Lighthouse 100 on all 21 pages (no script in the repository) | Lighthouse |
| End-to-end demonstration | `docs/demo-viva.md`, `tests/integration/test_viva_dataset.py` | `make test` |

## Worth discussing

These are real findings from the project, which may suit an evaluation section.

| Finding | Where |
|---|---|
| Generated data found three bugs that hand-written benchmarks missed: ignored deliveries, a month that could never close, and very slow posting | `docs/validation-log.md` |
| Profiling overturned the plan's NumPy approach: database writes took about 80-90% of the time, not the maths | `docs/performance.md` |
| A clean-install test found that `make dev` failed on Windows | The commit history for Phase 7, and the README's install steps |
| Excel keeps unrounded amounts and the system keeps cents, so differences up to the tolerance are expected, and 4 sit exactly at 0.01 | `docs/test-report/test-report.md` |
| Places the specification was silent, and how the system refuses rather than guesses | `docs/release/release-checklist.md` |

## Be careful to say

- **Who wrote the expected values.** Most golden cases were drafted by the developers until M1 confirms them, so say which are confirmed. A benchmark written by the same people as the code is weaker evidence than the workbooks.
- **What "zero variance" means:** nothing outside the 0.01 tolerance, not every difference being 0.00.
- **The advisor sessions and the outside install test:** cite them only once they have happened (`docs/validation-log.md`).
- **Limits of the performance result:** one machine, one month, no contract events, one user.
