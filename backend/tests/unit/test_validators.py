"""P1-T7: one test per error code (E001-E010, E012-E014) and the D9 quarantine.

Each test writes a small upload as CSV text, runs it through the real parser and
then the validators, as an upload will flow in P1-T8.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.ingestion.parser import parse_rows, read_table
from app.ingestion.templates import TEMPLATES
from app.ingestion.validators import (
    ContractInfo,
    ExistingData,
    InvoiceInfo,
    LineInfo,
    ProductInfo,
    Result,
    validate_batch,
)
from app.models.enums import RecognitionMethod, UploadTemplate

M, D, P = (
    RecognitionMethod.RATABLE_MONTHLY,
    RecognitionMethod.RATABLE_DAILY,
    RecognitionMethod.POINT_IN_TIME,
)

EXISTING = ExistingData(
    current_period="202606",
    customers=frozenset({"CUST-1"}),
    products={
        "SUB": ProductInfo(separate=True, method=M),
        "DAILY": ProductInfo(separate=True, method=D),
        "PRINT": ProductInfo(separate=True, method=P),
        "SETUP": ProductInfo(separate=False, method=P),
    },
    accounts={"1100": "ASSET", "4100": "REVENUE"},
    contracts={
        "K-OLD": ContractInfo(
            customer_code="CUST-1",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            lines={
                1: LineInfo("SUB", date(2026, 1, 1), date(2026, 12, 31), None),
                2: LineInfo("PRINT", date(2026, 1, 1), date(2026, 12, 31), date(2026, 9, 30)),
            },
        )
    },
    invoices={
        "INV-OLD": InvoiceInfo("K-OLD", date(2026, 1, 15), Decimal("1200.00"), Decimal("200.00"))
    },
    credit_notes=frozenset({"CN-OLD"}),
    deliveries=frozenset({"D-OLD"}),
    delivered={("K-OLD", 2): Decimal("0.5")},
)

NEW_CONTRACT = "K-NEW,CUST-1,2026-01-01,2026-12-31,NEW,2026-01-01"
NEW_LINE = "K-NEW,1,SUB,1,1200.00,,2026-01-01,2026-12-31,"


def run(existing: ExistingData = EXISTING, **files: str) -> Result:
    """Validate an upload given as {template name: CSV body without header}."""
    parsed = {}
    for name, body in files.items():
        template = TEMPLATES[UploadTemplate(name)]
        content = (",".join(template.headers) + "\n" + body.strip() + "\n").encode()
        parsed[template.name] = parse_rows(read_table(content, f"{name}.csv", template), template)
    return validate_batch(parsed, existing)


def codes(result: Result, template: str) -> list[list[str]]:
    """Error codes per row of one template, e.g. [[], ["E004"]]."""
    return [[e.code for e in row.errors] for row in result[UploadTemplate(template)]]


def messages(result: Result, template: str) -> list[str]:
    return [e.message for row in result[UploadTemplate(template)] for e in row.errors]


# --------------------------------------------------------------------------- the happy path


def test_valid_multi_file_upload_has_no_errors() -> None:
    result = run(
        customers="CUST-2,Contoso,us",
        products="NEW-SUB,New sub,,100.00,FIXED,100.00,,RATABLE_DAILY,Y,4100,",
        contracts="K-2,CUST-2,2026-03-15,2027-03-14,NEW,2026-03-15",
        contract_lines="K-2,1,NEW-SUB,2,100.00,10.00,2026-03-15,2027-03-14,",
        invoices="INV-2,K-2,2026-03-15,1,190.00",
        credit_notes="CN-2,INV-2,2026-04-01,50.00,Goodwill",
    )
    assert all(row.ok for rows in result.values() for row in rows), [
        (r.template, r.errors) for rows in result.values() for r in rows if not r.ok
    ]
    assert result[UploadTemplate.CUSTOMERS][0].values["country"] == "US"  # normalised


def test_x02_first_month_from_the_excel_workbook_validates_cleanly() -> None:
    folder = (
        Path(__file__).resolve().parents[3] / "benchmarks/cases/X02_revrec_mock_data/inputs/202501"
    )
    existing = ExistingData(
        current_period="202501", accounts={"4100": "REVENUE", "4200": "REVENUE"}
    )
    files = {p.stem: p.read_text(encoding="utf-8").split("\n", 1)[1] for p in folder.glob("*.csv")}
    result = run(existing, **files)
    failures = [(r.template, r.errors) for rows in result.values() for r in rows if not r.ok]
    assert failures == []
    assert len(result[UploadTemplate.CONTRACT_LINES]) > 0


# --------------------------------------------------------------------------- one test per code


def test_e001_missing_required_value() -> None:
    result = run(products="P9,Fixed SSP,,100.00,FIXED,,,RATABLE_DAILY,Y,4100,")
    assert codes(result, "products") == [["E001"]]
    assert "ssp_value is required when ssp_source is FIXED" in messages(result, "products")[0]


def test_e002_wrong_type() -> None:
    assert codes(run(customers="CUST-9,Acme,G1"), "customers") == [["E002"]]


def test_e003_invalid_date_quarantines_the_contract() -> None:
    result = run(
        contracts="K-NEW,CUST-1,2026-01-01,2026-31-12,NEW,2026-01-01", contract_lines=NEW_LINE
    )
    assert codes(result, "contracts") == [["E003"]]
    assert codes(result, "contract_lines") == [["E013"]]


def test_e004_unknown_references() -> None:
    result = run(
        products="P9,Sub,,1.00,LIST_PRICE,,,RATABLE_DAILY,Y,9999,",
        contracts="K-NEW,CUST-404,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K-NEW,1,NOPE,1,10.00,,2026-01-01,2026-12-31,",
        invoices="INV-9,K-404,2026-02-01,1,10.00",
        credit_notes="CN-9,INV-404,2026-02-01,1.00,x",
    )
    assert codes(result, "products") == [["E004"]]
    assert codes(result, "contracts") == [["E004"]]
    assert codes(result, "contract_lines") == [["E004"]]
    assert codes(result, "invoices") == [["E004"]]
    assert codes(result, "credit_notes") == [["E004"]]


def test_e005_duplicate_in_file() -> None:
    result = run(
        customers="CUST-7,A,GB\nCUST-7,B,GB",
        contracts=NEW_CONTRACT,
        contract_lines=f"{NEW_LINE}\n{NEW_LINE}",
    )
    assert codes(result, "customers") == [["E005"], ["E005"]]
    assert "rows 2, 3" in messages(result, "customers")[0]
    assert codes(result, "contract_lines") == [["E005"], ["E005"]]


def test_e006_already_in_database() -> None:
    result = run(
        customers="CUST-1,Again,GB",
        contracts="K-OLD,CUST-1,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K-OLD,1,SUB,1,10.00,,2026-01-01,2026-12-31,",
        invoices="INV-OLD,K-OLD,2026-02-01,1,10.00",
    )
    assert codes(result, "customers") == [["E006"]]
    assert codes(result, "contracts") == [["E006"]]
    assert codes(result, "invoices") == [["E006"]]


def test_e007_date_ranges() -> None:
    result = run(
        contracts="K-NEW,CUST-1,2026-06-01,2026-12-31,NEW,2026-06-01\n"
        "K-BAD,CUST-1,2026-12-31,2026-01-01,NEW,2026-12-31",
        contract_lines="K-NEW,1,DAILY,1,10.00,,2026-05-01,2026-12-31,",  # starts before the term
        credit_notes="CN-9,INV-OLD,2026-01-01,1.00,early",  # before the invoice date
    )
    assert codes(result, "contract_lines") == [["E007"]]
    assert codes(result, "contracts") == [["E013"], ["E007", "E009"]]  # K-BAD: also no lines
    assert codes(result, "credit_notes") == [["E007"]]


def test_e008_negative_amounts_and_quantities() -> None:
    result = run(
        contracts=NEW_CONTRACT,
        contract_lines="K-NEW,1,SUB,0,-5.00,,2026-01-01,2026-12-31,",
        deliveries="DLV-9,K-OLD,2,2026-03-31,0",
    )
    assert codes(result, "contract_lines") == [["E008", "E008"]]
    assert codes(result, "deliveries") == [["E008"]]


def test_e009_business_rules() -> None:
    result = run(
        products="P9,Sub,,1.00,LIST_PRICE,,,RATABLE_DAILY,Y,1100,",  # not a revenue account
        contracts="K-NEW,CUST-1,2026-01-01,2026-12-31,NEW,2026-01-01\n"
        "K-OLD,CUST-1,2026-01-01,2026-12-31,CANCELLATION,2026-07-31",
        contract_lines="K-NEW,1,SUB,1,10.00,10.01,2026-01-01,2026-12-31,\n"  # discount > line
        "K-OLD,3,SUB,1,10.00,,2026-01-01,2026-12-31,",  # a cancellation has no lines
        credit_notes="CN-9,INV-OLD,2026-02-01,1000.01,too much",  # 1000.00 left
        deliveries="DLV-1,K-OLD,2,2026-03-31,0.3\n"
        "DLV-2,K-OLD,2,2026-04-30,0.3\n"  # 0.5 + 0.3 + 0.3 > 1
        "DLV-3,K-OLD,1,2026-03-31,0.1\n"  # line 1 is ratable, not point in time
        "DLV-4,K-OLD,2,2026-10-31,0.1",  # after the completion date
    )
    assert codes(result, "products") == [["E009"]]
    assert codes(result, "contracts") == [["E013"], ["E009"]]
    assert codes(result, "contract_lines") == [["E009"], ["E013"]]
    assert codes(result, "credit_notes") == [["E009"]]
    assert codes(result, "deliveries") == [[], ["E009"], ["E009"], ["E009"]]


def test_e009_other_contract_rules() -> None:
    result = run(
        contracts="K-OLD,CUST-2,2026-01-01,2026-12-31,UPGRADE,2026-07-01",
        contract_lines="K-OLD,2,DAILY,1,10.00,,2026-07-01,2026-12-31,",
    )
    assert codes(result, "contracts") == [["E004", "E009"]]  # unknown and different customer
    assert codes(result, "contract_lines") == [["E009"]]  # line 2 already exists


def test_e010_event_before_the_current_period() -> None:
    result = run(
        contracts="K-OLD,CUST-1,2026-01-01,2026-12-31,CANCELLATION,2026-05-31",
    )
    assert codes(result, "contracts") == [["E010"]]
    accepted = run(contracts="K-OLD,CUST-1,2026-01-01,2026-12-31,CANCELLATION,2026-06-01")
    assert codes(accepted, "contracts") == [[]]


def test_e012_ratable_monthly_needs_whole_months() -> None:
    result = run(
        contracts=NEW_CONTRACT,
        contract_lines="K-NEW,1,SUB,1,10.00,,2026-01-15,2026-12-31,\n"
        "K-NEW,2,DAILY,1,10.00,,2026-01-15,2026-12-31,",  # ratable daily: any window is fine
    )
    assert codes(result, "contract_lines") == [["E012"], ["E013"]]


def test_e013_quarantine_keeps_other_contracts() -> None:
    """D9: a failed line holds back its whole contract; other contracts still load."""
    result = run(
        contracts=f"{NEW_CONTRACT}\nK-OK,CUST-1,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K-NEW,1,SUB,1,10.00,,2026-01-01,2026-12-31,\n"
        "K-NEW,2,NOPE,1,10.00,,2026-01-01,2026-12-31,\n"
        "K-OK,1,SUB,1,10.00,,2026-01-01,2026-12-31,",
        invoices="INV-1,K-NEW,2026-01-31,1,10.00\nINV-2,K-OK,2026-01-31,1,10.00",
    )
    assert codes(result, "contracts") == [["E013"], []]
    assert codes(result, "contract_lines") == [["E013"], ["E004"], []]
    assert "contract_lines row 3 failed" in messages(result, "contracts")[0]
    # An invoice for the quarantined contract cannot load either.
    assert codes(result, "invoices") == [["E004"], []]
    assert "was rejected in this upload" in messages(result, "invoices")[0]


def test_e013_invoice_is_all_or_nothing() -> None:
    result = run(invoices="INV-9,K-OLD,2026-02-01,1,10.00\nINV-9,K-OLD,2026-02-01,7,5.00")
    assert codes(result, "invoices") == [["E013"], ["E004"]]


def test_e014_no_separate_obligation() -> None:
    result = run(
        contracts=NEW_CONTRACT,
        contract_lines="K-NEW,1,SETUP,1,500.00,,2026-01-01,2026-01-01,",
    )
    assert codes(result, "contracts") == [["E014"]]
    assert codes(result, "contract_lines") == [["E013"]]


# --------------------------------------------------------------------------- cross-file references


def test_rejected_customer_is_named_in_the_contract_error() -> None:
    result = run(
        customers="CUST-9,Bad country,GBR",
        contracts="K-NEW,CUST-9,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines=NEW_LINE,
    )
    assert codes(result, "contracts") == [["E004"]]


def test_lines_for_an_existing_contract_need_its_contract_row() -> None:
    result = run(contract_lines="K-OLD,5,SUB,1,10.00,,2026-01-01,2026-12-31,")
    assert codes(result, "contract_lines") == [["E009"]]


def test_upgrade_keeps_continuing_lines_for_invoices_and_deliveries() -> None:
    result = run(
        contracts="K-OLD,CUST-1,2026-01-01,2026-12-31,UPGRADE,2026-07-01",
        contract_lines="K-OLD,3,DAILY,1,10.00,,2026-07-01,2026-12-31,",
        invoices="INV-9,K-OLD,2026-07-01,1,5.00\nINV-9,K-OLD,2026-07-01,3,10.00",
        deliveries="DLV-9,K-OLD,2,2026-07-31,0.25",
    )
    assert all(r.ok for rows in result.values() for r in rows)


def test_deliveries_add_up_across_the_database_and_the_file() -> None:
    existing = replace(EXISTING, delivered={("K-OLD", 2): Decimal("0.75")})
    result = run(
        existing, deliveries="DLV-1,K-OLD,2,2026-03-31,0.25\nDLV-2,K-OLD,2,2026-04-30,0.01"
    )
    assert codes(result, "deliveries") == [[], ["E009"]]
