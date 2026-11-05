# FYP-I demo walkthrough

**Demo: 11 Dec 2026. Defense: 18 Dec 2026. Length: under 5 minutes.**

What it proves, the plan's FYP-I milestone: *upload → validation → database → ratable monthly schedule → MUI grid.*

Files to upload are in [`demo-fyp1/data/`](demo-fyp1/data/). Screenshots for the report are in [`demo-fyp1/screenshots/`](demo-fyp1/screenshots/).

## Before the demo

Do this **the day before**, then once more 30 minutes before you present.

1. Start Docker Desktop and wait for "Engine running".
2. In a terminal in the project folder, run `make dev` and leave it running. The first build after a package change can take several minutes.
3. In a **second** terminal, reset to a clean database:

   ```powershell
   make demo-reset CONFIRM=yes
   ```

   **This deletes all data in the development database.** The demo needs it because the same contracts cannot be uploaded twice. It leaves the current period at 2026-12 and the admin user in place.
4. Open http://localhost:3000/login in Chrome or Edge and press Ctrl+F5. Set the browser zoom so the whole grid fits on the projector.
5. Open the `docs/demo-fyp1/data` folder in File Explorer, ready to select files.

## The script

| Time | Do | Say | Check on screen |
|---|---|---|---|
| 0:00 | Show the sign-in page. Sign in with `admin@revrec.local` / `ChangeMe-Admin1`. | "This is a revenue sub-ledger for subscription contracts. Every API call checks the user's role." | **Administrator / ADMIN** at the top right |
| 0:20 | Click **Uploads**. Point at **Templates**. | "Users get a template for each of the seven file types. IDs stay as text, so leading zeros survive." | 7 templates, each with CSV and Excel |
| 0:40 | **Choose files**: `customers.csv`, `products.csv`, `contracts.csv`, `contract_lines.csv`. Click **Upload 4 files**. | "The file goes to a background job, so the page stays responsive. Each file's type is recognised from its header row." | 4 green **ACCEPTED** chips |
| 1:15 | **Choose files**: `bad_contracts.csv`, `bad_contract_lines.csv`. Click **Upload 2 files**. | "Now a file with mistakes." | 2 orange **PARTIAL** chips, each "1 of 3 rows accepted" |
| 1:35 | Click **View errors** beside `bad_contract_lines.csv`. | "Row 3 starts on the 15th, but a monthly subscription must cover whole months: E012. Row 4 is fine, but its contract names a customer that does not exist, so the whole contract is held back: E013. We never load half a contract." | Row 3 **E012**, row 4 **E013** |
| 2:10 | Click **Download error log (CSV)**. Open it if time allows. | "The user gets this list to fix and upload again. Each row keeps its file and row number." | The CSV downloads |
| 2:25 | Click **Contracts**. | "The good contract from the bad file still loaded, and the two with errors did not. Five contracts, no schedules yet." | 5 rows, all **Not yet**; no `000201` or `000202` |
| 2:45 | Click **Run recognition**. | "The engine allocates each contract's price and builds its schedule, in integer cents, never floating point." | "5 contracts scheduled, 72 schedule lines created. 45 lines booked in 2026-12, 40 of them catch-up." All chips **Generated** |
| 3:10 | Click **000102-SUB**. | "This is the check from our proposal. 11,200 over 12 months is 933.33 a month. The last month absorbs the rounding, so it is 933.37, and the total matches the price to the cent." | 933.33 × 11, then **933.37**. Total **11,200.00** |
| 3:50 | **All contracts**, then **000104-SUB**. | "This customer also paid a 500 setup fee. It is not a separate obligation, so it is spread through the subscription: 1,700 over 12 months." | 141.67 × 11, then **141.63**. Total **1,700.00** |
| 4:20 | **All contracts**, then **Run recognition** again. | "Running it twice is safe: nothing is generated twice." | "Nothing new to schedule." |
| 4:35 | Close. | "Upload, validation, database, schedule, grid, all on the real engine, nothing throwaway. Next: period close and the reports." | |

## What each contract shows

| Contract | Customer | Price | Schedule | Shows |
|---|---|---|---|---|
| `000101-SUB` | Northwind Traders | 1,200.00 | 100.00 × 12 | The simple case (golden case U01) |
| `000102-SUB` | Contoso Ltd | 11,200.00 | 933.33 × 11, then 933.37 | The proposal's check, last month absorbs rounding (plan §5.3) |
| `000103-SUB` | Fabrikam Inc | 5 × 1,200.00 − 600.00 = 5,400.00 | 450.00 × 12 | A discount reduces revenue |
| `000104-SUB` | Adventure Works | 1,200.00 + 500.00 fee = 1,700.00 | 141.67 × 11, then 141.63 | A setup fee is spread through the subscription (D4) |
| `000105-SUB` | Northwind Traders | 24,000.00 | 1,000.00 × 24 | Long term; arrives in the bad upload and still loads (D9) |

The two contracts that do **not** load:

| Contract | Problem | Errors |
|---|---|---|
| `000201-SUB` | The line starts on 15 Jan, but the product is ratable monthly | Line: **E012**. Contract row: **E013** |
| `000202-SUB` | Customer `CUST-9999` does not exist | Contract row: **E004**. Line: **E013** |

Total scheduled across the five contracts: **43,500.00**, in **72** lines. `backend/tests/integration/test_demo_dataset.py` checks all these numbers, so `make test` fails if later work changes them.

## Questions you may be asked

**What do "Booked in" and "Catch-up" mean?**
A schedule line has two dates: the month revenue is *earned* (service period) and the month it is *booked* (D5). Booked months are never reopened, so revenue earned before the current period is booked now, marked catch-up. Later months show "Not yet" (plan §5.4).

**Why is every contract booked in 2026-12 when some start in January?**
Booked means the period that was open when the contract was uploaded. Revenue already earned for earlier months posts as catch-up in that period.

**Why not floats?**
`0.1 + 0.2` is not exactly `0.3` in floating point, and the outputs must match the Excel benchmarks within 0.01. The engine uses integer cents, and the database uses `NUMERIC(18,2)`.

**What happens to bundles with several products?**
The price is shared by relative SSP, and any rounding difference goes to the largest obligation (plan §5.2). The Excel workbooks are full of them, and the benchmarks match within 0.01.

**Can posted data be changed?**
No. Database triggers refuse it, even from a bug in our own code. Corrections will be new reversal entries (plan §6.3).

**What about the other pages in the menu?**
Master data, uploads, contracts and journals are built. The dashboard, periods and reports show placeholders naming the task that builds them.

## If something goes wrong

| Problem | Do this |
|---|---|
| The site does not open | Check Docker Desktop is running, then run `docker compose up -d` and wait 30 seconds |
| Docker Desktop shows an error | Quit and reopen it, then run `docker compose up -d`. Data is kept |
| An upload stays at 0% | The worker may be down: run `docker compose restart worker` |
| Files were already uploaded, so everything is rejected as a duplicate | Run `make demo-reset CONFIRM=yes` and sign in again |
| Nothing can be fixed in time | Present the screenshots in `demo-fyp1/screenshots/`, in order |

## Rehearsal record

The plan asks for a run-through under 5 minutes, rehearsed twice.

| Date | Who | Time | Notes |
|---|---|---|---|
| | | | |
| | | | |

Scripted browser rehearsals check that the steps work and the numbers are right. They do not replace the team presenting it aloud with a stopwatch; fill in this table when you do.
