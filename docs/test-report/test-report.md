# Revenue recognition system: test report

Date: 2026-11-05 · Code version: `883655d-dirty`

**DRAFT: the run passes, but the report cannot be signed yet.**

- 13 case(s) use expected values M1 has not confirmed (drafted by the developers).
- 3 accounting decision(s) are not signed off.

## Result

- Cases run: **19**, failed: **0**
- Amounts compared: **8000**, outside tolerance: **0**
- Largest difference: **0.01**

Pass rule: Every schedule and journal amount within 0.01 of the expected value, and every obligation's schedule total exactly equal to its allocation (plan §11.1).

"Zero variance" here means no amount is outside the 0.01 tolerance. It does not mean every difference is 0.00: Excel holds unrounded amounts and the system holds cents, so differences up to the tolerance are expected (plan §11.4).

## Per case

| Case | Level | Expected values from | Result | Compared | Max variance | Outside 0.01 |
|---|---|---|---|---:|---:|---:|
| U01_ratable_monthly_12m | Unit | Developer draft | PASS | 25 | 0.00 | 0 |
| U02_ratable_daily_mid_month | Unit | Developer draft | PASS | 27 | 0.00 | 0 |
| U03_point_in_time | Unit | Developer draft | PASS | 3 | 0.00 | 0 |
| B01_worked_example | Bundle | Developer draft | PASS | 33 | 0.00 | 0 |
| B02_three_line_discount | Bundle | Developer draft | PASS | 75 | 0.00 | 0 |
| B03_setup_fee | Bundle | Developer draft | PASS | 25 | 0.00 | 0 |
| E01_renewal | Events | Developer draft | PASS | 100 | 0.00 | 0 |
| E02_cancellation_credit_note | Events | Developer draft | PASS | 37 | 0.00 | 0 |
| E03_upgrade | Events | Developer draft | PASS | 68 | 0.00 | 0 |
| J01_invoice_in_advance | Journals | Developer draft | PASS | 50 | 0.00 | 0 |
| J02_credit_note_unrecognised | Journals | Developer draft | PASS | 51 | 0.00 | 0 |
| J03_recognition_before_invoice | Journals | Developer draft | PASS | 32 | 0.00 | 0 |
| C01_close_and_late_invoice | Close | Developer draft | PASS | 39 | 0.00 | 0 |
| X01_revrec_model_final | Excel | Workbook | PASS | 80 | 0.01 | 0 |
| X02_revrec_mock_data | Excel | Workbook | PASS | 557 | 0.01 | 0 |
| L01_load_50k | Load | - | make load | | | |
| G_bundles_s2 | Generated | Generator | PASS | 1187 | 0.00 | 0 |
| G_events_s3 | Generated | Generator | PASS | 1859 | 0.00 | 0 |
| G_full_s4 | Generated | Generator | PASS | 2286 | 0.00 | 0 |
| G_single_s1 | Generated | Generator | PASS | 1466 | 0.00 | 0 |

## How the differences spread

| Difference | Amounts |
|---|---:|
| 0 | 7502 |
| up to 0.005 | 403 |
| above 0.005, below 0.01 | 91 |
| exactly 0.01 | 4 |
| over 0.01 | 0 |

4 amount(s) sit exactly at 0.01. They pass only because the rule says "within 0.01", read as including 0.01. M1 should confirm that reading.

## Largest differences

| Case | Check | Item | Expected | Actual | Difference |
|---|---|---|---:|---:|---:|
| X01_revrec_model_final | schedule | 005984698-INV_106000493/2/202712 | 9.45 | 9.44 | 0.01 |
| X01_revrec_model_final | postings | 202712/005984698-INV_106000493/2/REVENUE | 9.45 | 9.44 | 0.01 |
| X02_revrec_mock_data | schedule | 006210412-INV_106100528/1/202712 | 6.3 | 6.29 | 0.01 |
| X02_revrec_mock_data | postings | 202712/006210412-INV_106100528/1/REVENUE | 6.3 | 6.29 | 0.01 |
| X02_revrec_mock_data | schedule | 006210406-INV_106100522/1/202508 | 1.7292... | 1.72 | 0.0092... |
| X02_revrec_mock_data | postings | 202507/006210402-INV_106100518/2/REVENUE | 1.229 | 1.22 | 0.009 |
| X02_revrec_mock_data | postings | 202507/006210415-INV_106100531/1/REVENUE | 1.229 | 1.22 | 0.009 |
| X02_revrec_mock_data | schedule | 006210402-INV_106100518/2/202507 | 1.2290... | 1.22 | 0.0090... |
| X02_revrec_mock_data | schedule | 006210415-INV_106100531/1/202507 | 1.2290... | 1.22 | 0.0090... |
| X02_revrec_mock_data | schedule | 006210408-INV_106100524/3/202502 | 1.2412... | 1.25 | 0.0088... |
| X02_revrec_mock_data | postings | 202504/006210410-INV_106100526/1/REVENUE | 0.9616 | 0.97 | 0.0084 |
| X02_revrec_mock_data | postings | 202504/006210420-INV_106100536/2/REVENUE | 0.8384 | 0.83 | 0.0084 |
| X02_revrec_mock_data | postings | 202511/006210404-INV_106100520/1/REVENUE | 0.8384 | 0.83 | 0.0084 |
| X02_revrec_mock_data | postings | 202511/006210410-INV_106100526/1/REVENUE | 0.9616 | 0.97 | 0.0084 |
| X02_revrec_mock_data | postings | 202511/006210419-INV_106100535/1/REVENUE | 0.9616 | 0.97 | 0.0084 |

## Decisions waiting for sign-off

- D2: Rounding is ROUND_HALF_UP to 2 dp
- D3: The Excel method PROPORTIONAL_PERFORMANCE maps to POINT_IN_TIME with partial deliveries: tranches are recognised on delivery dates; any undelivered remainder is recognised on the completion date
- D8: Prospective upgrade: SSP basis for an old ratable obligation that continues is SSP × remaining service days ÷ total service days; satisfied point-in-time obligations are excluded from reallocation

## Sign-off

| Role | Name | Signature | Date |
|---|---|---|---|
| Accounting lead (M1) | | | |
| Project advisor | | | |
