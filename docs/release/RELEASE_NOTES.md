# Release notes: v1.0.0 (DRAFT)

**Not released yet.** The open items are in [release-checklist.md](release-checklist.md). Update this file with the final results before tagging.

## What it is

A web-based revenue sub-ledger for subscription contracts, following a simplified ASC 606 / IFRS 15. It reads contract and billing files, validates them, allocates price by relative SSP, generates revenue schedules, books balanced journals, closes periods and reports. Billing itself is out of scope.

## What it does

- **Upload and validation:** seven templates, CSV or Excel, with error codes E001-E014. A failed row holds back its whole contract version, and other contracts still load.
- **Recognition:** ratable monthly, ratable daily and point in time with partial deliveries, with catch-up for earlier months.
- **Contract events:** renewal, cancellation and prospective upgrade, each creating a new version.
- **Journals:** invoices, credit notes, revenue and catch-up, with the deferred and unbilled split. Generate, approve, post and reverse, with segregation of duties.
- **Period close:** a live 6-item checklist with a GL tie-out, close and reopen.
- **Reports:** revenue schedule, deferred rollforward, trend, journal register, GL summary, MRR / ARR (non-GAAP), close status and validation log, with filters, CSV and print, and a trail back to the uploaded row.
- **Security:** four roles on every endpoint, an audit log, database triggers that protect posted data, a password policy and a login limit.

## Results so far

Measured before M1's sign-off. Update them after the final run.

| Measure | Target | Result |
|---|---|---|
| Benchmark amounts outside 0.01 | 0 | 0 of 8,000, in 15 cases and 4 generated datasets |
| Excel workbooks X01 and X02 | Within 0.01 | Pass, largest difference 0.01 |
| 50,000 lines: upload, recognition, journals | Under 5 min | 256 s |
| Engine, 50,000 lines | Under 60 s | 55 s |
| Lighthouse accessibility | 90 or more | 100 on all 21 pages |

13 of the 15 benchmark cases use expected values drafted by the developers, which M1 has yet to confirm. The test report is not signed.

## Known limits

- **Corrections:** a reversal corrects the ledger, but does not change the schedule or re-book the revenue.
- **Refused cases:** some situations the plan does not define are refused and reported, such as an event changing posted revenue. See the checklist.
- **Master data:** products and accounts come in by upload or seed. Editing them through the API returns 501.
- **Users:** admins add users through the API; there is no page for it.
- **Performance:** one month at 50,000 lines was measured, without contract events. Several users at once was not tested.
- **Security:** this was a developer's review, not a penetration test. Set the admin password and JWT secret before any real deployment.

## Install

Follow the [README](../../README.md), then the [user manual](../user-manual.md).

## In this release

- Database schema: [schema.sql](schema.sql), and the [ERD](../erd.md)
- [Test report](../test-report/test-report.pdf) · [Performance](../performance.md) · [Validation log](../validation-log.md) · [Security pass](../security-pass.md)
- [Viva demo script](../demo-viva.md)
