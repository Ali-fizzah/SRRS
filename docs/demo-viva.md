# Viva demo script

**Viva: 16 Jun 2027.** The FYP-I demo has [its own script](demo-fyp1.md).

This shows the whole system over two months: upload, validation, allocation, schedules, journals, approval, close, a cancellation, an upgrade, reports and the trail back to the source file.

Clicks and loading take about 4 minutes. With talking, expect about 15 minutes, but only your own dry runs can confirm that, so fill in the [record](#dry-run-record) below. If your slot is shorter, see [If time is short](#if-time-is-short).

## Before the viva

Do this **the day before**, then again 30 minutes before you present.

1. Start Docker Desktop and wait for "Engine running". In a terminal in the project folder, run `make dev` and leave it running.
2. In a second terminal, reset to a clean database:

   ```powershell
   make demo-viva CONFIRM=yes
   ```

   **This deletes all data in the development database.** It leaves May 2027 open, with the users below.
3. Open two browser windows, because the person who generates a batch cannot approve it:

   | Window | Sign in as | Password |
   |---|---|---|
   | Edge, normal: "the accountant" | `accountant@revrec.local` | `Accountant-Viva1` |
   | Edge, InPrivate: "the approver" | `approver@revrec.local` | `Approver-Viva-01` |

   Go to http://localhost:3000, sign in to each and press Ctrl+F5. Set the zoom so a whole grid fits on the projector. The first time a page opens it can take a few seconds, so click through every menu item once in each window.
4. Open `docs\demo-viva\data` in File Explorer, ready to select files.
5. Have `docs\test-report\test-report.pdf` and `docs\performance.md` open in another window.

## Month one: May 2027

| Do | Say | Check on screen |
|---|---|---|
| **Accountant.** Show the dashboard. | "This is a revenue sub-ledger for subscription contracts, following a simplified ASC 606 / IFRS 15. May 2027 is the open month." | **2027-05** |
| **Uploads**. Choose all 5 files in `may`. Click **Upload 5 files**. | "Files go to a background job. IDs stay as text, so leading zeros survive." | 5 **ACCEPTED** |
| Choose both files in `may-with-errors`. Click **Upload 2 files**. | "Now a file with mistakes." | 2 **PARTIAL** |
| Click **View errors** beside `contract_lines.csv`. | "V-2001 starts on the 15th, but a monthly product needs whole months: E012. V-2002's contract names a customer that does not exist, so its line is held back too: E013. We never load half a contract, but V-1005 in the same file still loaded." | **E012**, **E013** |
| **Contracts**. Click **Run recognition**. | "The engine allocates each contract's price and builds its schedule, in integer cents, never floating point." | "5 contracts scheduled, 61 schedule lines created. 14 lines booked in 2027-05, 9 of them catch-up." |
| Click **V-1001**, then **Obligations**. | "This is the example from our proposal. A 12,600 price is shared by standalone selling price: 11,200 and 1,400." | **11,200.00**, **1,400.00** |
| Click **Schedule**. | "The contract began in January but arrived in May. Those months are closed, so that revenue is booked now, marked catch-up. A monthly obligation's last month absorbs the rounding, so the total matches to the cent." | **Catch-up** chips; total **12,600.00** |
| Click **Source rows**. | "Every figure traces back to the file and row it came from." | The uploaded rows |
| **Journals**. Click **Generate journals**. | "These are balanced journals, with deferred and unbilled worked out per contract." | "Batch 1: 10 entries, 23,768.32" |
| **Approver.** **Journals**, open the batch. Click **Approve**, confirm, then **Post**, confirm. | "A different person approves it. Once posted it is read-only, and database triggers enforce that, not just the page." | **Balanced**, then **POSTED** |
| **Accountant.** **Periods**. Click **Start close**. | "New uploads are now blocked." | **Closing** |
| **Approver.** **Periods**. Point at the checklist, then click **Close period** and confirm. | "Close needs every item to pass, including this one: the deferred balance from the sub-ledger equals the general ledger." | Deferred **9191.68**, unbilled **1960.00** on both sides; then **2027-06** |

## Month two: June 2027

| Do | Say | Check on screen |
|---|---|---|
| **Accountant.** **Uploads**. Choose all 4 files in `june`. Click **Upload 4 files**. | "June brings a cancellation, an upgrade, a credit note and a new invoice." | 4 **ACCEPTED** |
| **Contracts**. Click **Run recognition**. | "Each event creates a new version. Posted lines are never changed; only pending lines are replaced." | "2 contract events applied. 7 lines booked in 2027-06, 0 of them catch-up." |
| Click **V-1003**, then **Obligations**. | "An upgrade on 15 June. 2,000 was still unearned, plus 800 for the added line, so 2,800 is shared across both, on the remaining term." | **1,866.67**, **933.33** |
| **All contracts**, **V-1002**, then **Billing**. | "Cancelled on 30 June after 200 of revenue. The 1,000 credit note took out what was left, so nothing stays deferred." | Status **CANCELLED**; deferred **0.00** |
| **Journals**. Click **Generate journals**. | "That invoice clears V-1003's unbilled balance first, and the rest becomes deferred." | "Batch 1: 7 entries, 4,989.00" |
| **Approver.** Open the new batch: **Approve**, **Post**. **Accountant.** **Periods**: **Start close**. **Approver.** **Periods**: **Close period**. | "The same control again." | Deferred **7142.68**, unbilled **900.00**; then **2027-07** |

## The reports and the evidence

| Do | Say | Check on screen |
|---|---|---|
| **Approver.** **Deferred rollforward**. | "Opening, billings, credit notes, recognised, closing, from the sub-ledger." | Closing **9,191.68**, then **7,142.68** |
| Click **2027-06**, then a contract, then **Source rows**. | "From a summary figure to the contract to the uploaded row: the audit trail." | The uploaded rows |
| **MRR / ARR**. | "Recurring revenue is shown apart and labelled non-GAAP." | The non-GAAP notice |
| **Journals**, open May's batch. Click **Reverse** on an entry, give a reason, and book it. | "Corrections are new reversal entries in the current period, and they need approval too. I booked this one, so I cannot approve it." | **DRAFT**; **Approve** greyed out |
| Open the test report. | Say what it shows that day: see the warning below. | |
| Open `docs\performance.md`. | "50,000 contract lines from upload through journals in under the 5-minute target." | **256 s** against 300 s, or your final run |

**Say only what the report says on the day.** If it still shows DRAFT, say so, and do not call it signed. The two workbooks (X01, X02) are the external benchmarks. "Zero variance" means nothing is outside the 0.01 tolerance, not that every difference is 0.00.

## What each contract shows

| Contract | Customer | Price | Shows | Deferred / unbilled, end of May | End of June |
|---|---|---|---|---|---|
| `V-1001` | Contoso Ltd | 12,600.00 | Bundle, proposal's example, catch-up, late invoice | 6,533.35 deferred | 5,600.02 deferred |
| `V-1002` | Northwind Traders | 1,200.00 | Cancellation with a credit note | 1,100.00 deferred | 0.00 |
| `V-1003` | Fabrikam Inc | 3,650.00, then 800.00 added | Daily rate, catch-up, upgrade, unbilled cleared by an invoice | 1,510.00 unbilled | 126.00 deferred |
| `V-1004` | Adventure Works | 1,700.00 | Setup fee spread through the subscription | 1,558.33 deferred | 1,416.66 deferred |
| `V-1005` | Contoso Ltd | 5,400.00 | Loaded from the file with errors; not yet invoiced | 450.00 unbilled | 900.00 unbilled |

`V-2001` and `V-2002` do not load. `backend/tests/integration/test_viva_dataset.py` checks these figures, so `make test` fails if later work changes them.

### How the upgrade is worked out

`V-1003` is 3,650.00 over 365 days, so 10.00 a day.

1. Earned through 14 June: 165 days, 1,650.00. Left: 2,000.00.
2. Pool: 2,000.00 left + 800.00 added = 2,800.00.
3. D8 SSP basis for the old line: 3,650 x 200 remaining days / 365 = 2,000.00. SSP of the added line: 1,000.00.
4. Shared 2,000 : 1,000 gives **1,866.67** and **933.33**.

## Questions you may be asked

**Why integer cents?**
`0.1 + 0.2` is not exactly `0.3` in floating point, and outputs must match the benchmarks within 0.01. The engine uses whole cents; the database uses `NUMERIC(18,2)`.

**What are "service period" and "posting period"?**
When revenue is earned, and when it is booked (D5). Booked months are never reopened for new entries, so revenue earned earlier is booked now as catch-up.

**Can posted data be changed?**
No. Database triggers refuse it, even from a bug in our own code. The tests try it and expect a refusal.

**How do you know the numbers are right?**
Three ways: the two Excel workbooks, cases worked out by hand, and generated datasets whose answers are calculated separately from the engine. Generated data found real bugs, listed in [validation-log.md](validation-log.md).

**Why no NumPy, when the plan said so?**
Profiling showed database writes took most of the time, not the maths. See [performance.md](performance.md).

**What is not built?**
See plan §15. Billing itself is out of scope: the system reads invoices and credit notes, and never creates them. Reversed revenue is not re-booked automatically; check [the checklist](release/release-checklist.md) for what M1 decided.

## If time is short

Cut these first, in order. Each is about a minute:

1. The reversal.
2. MRR / ARR.
3. V-1002's billing tab. Say the cancellation out loud instead.
4. The error log. Keep the 2 **PARTIAL** chips.

Never cut: the proposal's example (V-1001), a posted batch, the close with its tie-out, and the trail to a source row.

## If something goes wrong

| Problem | Do this |
|---|---|
| The site does not open | Check Docker Desktop is running, then run `docker compose up -d` and wait 30 seconds |
| An upload stays at 0% | Run `docker compose restart worker` |
| Files are rejected as duplicates | You already uploaded them: run `make demo-viva CONFIRM=yes` and sign in again |
| "Too many failed attempts" | Run `docker compose restart api` |
| Nothing can be fixed in time | Present the screenshots in [demo-viva/screenshots](demo-viva/screenshots), in order |

## Dry-run record

P8-T2 needs two full dry runs, presented aloud, with a stopwatch. Scripted browser rehearsals check the steps and figures, but they do not replace this.

| Date | Who | Time | What to change |
|---|---|---|---|
| | | | |
| | | | |
