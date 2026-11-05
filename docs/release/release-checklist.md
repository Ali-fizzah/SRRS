# Release checklist for v1.0.0

Everything that must happen before tagging, in order, and every decision waiting for M1. Tick items as they are done. Final submission: **9 Jun 2027**.

## 1. Get the work onto `main`

- [ ] Open pull requests and merge the feature branches. `feat/P8-release` holds all the work, because each phase was built on the one before it.
- [ ] Confirm CI passes on GitHub. It may not have run on this work yet.
- [ ] Have a second member review, as plan §13 requires.

## 2. M1 decisions

Each answer can change expected values or rules, so finish these before the signed report. Record the answers in `docs/accounting-rules.md` (plan P0-T3), **which does not exist yet**, and update plan §2.

### Sign-offs the plan requires

| # | Decision | Built as | Answer |
|---|---|---|---|
| 1 | **D2** Rounding | As the plan states | |
| 2 | **D3** Partial deliveries for `PROPORTIONAL_PERFORMANCE` | As the plan states | |
| 3 | **D8** SSP basis in an upgrade | As the plan states | |
| 4 | Expected values for U01-U03, B01-B03, E01-E03, J01-J03, C01 (P4-T6 and §11.3) | Drafted by the developers, marked DRAFT in each `case.yaml` | |
| 5 | B01: a 900.00 discount on line 1 reaches the plan's TP of 12,600 | Developers' assumption | |

### Questions the plan does not answer

"Refused" means the system reports the case and changes nothing, rather than guessing a rule.

| # | Question | Today | Answer |
|---|---|---|---|
| 6 | Does "within 0.01" include exactly 0.01? 4 amounts sit there (X01, X02) | Included | |
| 7 | A contract event would change revenue already **posted** | Refused: `EVENT_AFTER_POSTING`. Warns at close | |
| 8 | A late delivery would change **booked** revenue | Refused: `DELIVERY_AFTER_BOOKING` | |
| 9 | Upgrade of a partly delivered item: what SSP does the rest carry? | Refused: `UPGRADE_PARTIAL_DELIVERY` | |
| 10 | Reversed revenue: how is it booked again? §8 has no adjustment endpoint | Not re-booked. GL corrected; schedule stays POSTED | |
| 11 | Delivering 50% + 50% of an odd amount leaves -0.01 in the completion month. Acceptable, or should the last delivery take the remainder? | -0.01 line, as §5.3 is written | |
| 12 | Invoice or delivery for an **old term** after a renewal | E004 if the new term dropped that line; otherwise attaches to the new term | |
| 13 | Credit note dated before an invoice in §5.6 order, or on the same date with a lower number | Refused at upload: E009 | |
| 14 | Future-dated documents | Post in their own month | |
| 15 | SSP rounding | Once, at the end | |
| 16 | D8 SSP basis rounding | To cents, before allocation | |
| 17 | Revenue account precedence | Product's own account ranks above category and default mappings | |
| 18 | Order of revenue entries in a period | Catch-up before current | |
| 19 | A cancelled contract, including renewing it | Refused: E009 | |
| 20 | Upgrade rules: added line starting before the effective date; a monthly line upgraded other than on the 1st | Refused: E007, E012 | |
| 21 | J02: revenue continues after a credit note, so that contract ends 300.00 unbilled | As built | |
| 22 | Month with nothing to book: §5.8 requires a batch | Passes as "nothing to book" | |
| 23 | §5.6 rollforward does not add up when an invoice clears unbilled | Added a **To unbilled** column | |
| 24 | A reversal moves an amount between deferred and unbilled: the total ties, the split does not | Warning; does not block close | |
| 25 | Close with a contract event that could not apply | Warning; does not block close | |
| 26 | Reopen: next period goes back to FUTURE, and its drafts wait | As built | |
| 27 | MRR: a cancellation stops it; after an upgrade it uses net price, not the reallocated amount | As built | |

### For the team

| # | Question | Today | Answer |
|---|---|---|---|
| 28 | P7-T1 says NumPy; it was not used. See `docs/performance.md` | Target met without it | |
| 29 | Password policy: 12+ characters with a capital, a small letter and a digit | As built | |
| 30 | Master-data editing (`POST` and `PATCH` for products, accounts, mappings) returns 501. §8 lists it, but §12 schedules no task | Not built | |
| 31 | No Users page in §9, so admins use `/docs` | As built | |
| 32 | The FUTURE period status was added to the plan's OPEN, CLOSING, CLOSED | As built | |

## 3. Validation

- [ ] M1 holds the advisor review sessions and records them in `docs/validation-log.md` (P6-T2).
- [ ] Update any code and `expected/` values the answers change, with M1's approval noted in `case.yaml`.
- [ ] Run `make test`, `make bench`, `make lint`.
- [ ] Run `make load N=50000` on the demonstration machine. Update `docs/performance.md` with that result.
- [ ] Someone outside the team installs and runs the demo from the README (P7-T4).

## 4. Signed test report

- [ ] `make report`. It must say **READY TO SIGN**, not DRAFT.
- [ ] M1 and the advisor sign `docs/test-report/test-report.pdf`.

## 5. Viva preparation

- [ ] Two full dry runs of `docs/demo-viva.md`, recorded there (P8-T2).
- [ ] Rehearse the FYP-I demo twice as well, for 11 Dec 2026 (`docs/demo-fyp1.md`).

## 6. Tag and release

- [ ] Set the version to `1.0.0` in `backend/pyproject.toml` and `frontend/package.json`.
- [ ] `make release-archive`. It updates `docs/release/schema.sql` and `docs/erd.md`.
- [ ] Update `docs/release/RELEASE_NOTES.md` with the final results and M1's answers.
- [ ] Commit, merge to `main`, then run on `main`:

  ```powershell
  git tag v1.0.0
  git push origin v1.0.0
  gh release create v1.0.0 --title "v1.0.0" --notes-file docs/release/RELEASE_NOTES.md docs/release/schema.sql docs/test-report/test-report.pdf
  ```

- [ ] M1 finishes the thesis chapters, citing the tag (P8-T3). See `docs/thesis-evidence.md`.
