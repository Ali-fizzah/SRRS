"""P1-T8 acceptance: uploads are parsed, validated and loaded with their source rows.

Mixed files get the right accepted/rejected counts, errors land in
validation_errors, and the whole X02 workbook loads month by month.
"""

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.ingestion.loader import UploadSummary, load_upload
from app.ingestion.templates import TEMPLATES
from app.models import (
    AccountingPeriod,
    AuditLog,
    Contract,
    ContractLine,
    ContractVersion,
    Customer,
    Delivery,
    Invoice,
    InvoiceLine,
    Product,
    SspRule,
    UploadFile,
    ValidationError,
)
from app.models.enums import PeriodStatus, UploadTemplate
from tests.integration.conftest import make_user

REPO = Path(__file__).resolve().parents[3]


def _tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


seed = _tool("seed")


@pytest.fixture
def user_id(db: Session) -> int:
    return make_user(db, [Role.UPLOADER]).id


def seeded(db: Session, current: str) -> None:
    seed.seed_accounts(db)
    seed.seed_periods(db, current)


def upload(db: Session, user_id: int, **files: str | bytes) -> list[UploadSummary]:
    """Load one upload of {template: CSV body without header | full file bytes}."""
    batch = []
    for name, body in files.items():
        template = TEMPLATES[UploadTemplate(name.rstrip("_"))]
        content = (
            body
            if isinstance(body, bytes)
            else (",".join(template.headers) + "\n" + body.strip() + "\n").encode()
        )
        record = UploadFile(
            template=template.name,
            original_filename=f"{template.name.value}.csv",
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key="202601",
        )
        db.add(record)
        batch.append((record, content))
    db.flush()
    return load_upload(db, batch, user_id)


def errors(db: Session, upload_id: int) -> list[tuple[int, str | None, str]]:
    return [
        (e.row_number, e.column_name, e.error_code)
        for e in db.scalars(
            select(ValidationError)
            .where(ValidationError.upload_file_id == upload_id)
            .order_by(ValidationError.row_number, ValidationError.id)
        )
    ]


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- acceptance


def test_mixed_file_gets_correct_counts_and_errors(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    (summary,) = upload(
        db,
        user_id,
        customers="C1,Acme,gb\nC2,Beta,US\nC3,Gamma,GBR\n,,\nC4,,FR",
    )
    assert (summary.status, summary.total_rows, summary.accepted_rows, summary.rejected_rows) == (
        "PARTIAL", 4, 2, 2,
    )  # fmt: skip
    # Row 5 is blank and skipped; the row numbers still match the file.
    assert errors(db, summary.upload_id) == [(4, "country", "E002"), (6, "name", "E001")]

    record = db.get(UploadFile, summary.upload_id)
    assert record is not None and record.status == "PARTIAL"
    loaded = db.scalars(select(Customer).order_by(Customer.customer_code)).all()
    assert [(c.customer_code, c.country) for c in loaded] == [("C1", "GB"), ("C2", "US")]
    # CLAUDE.md rule 5: every loaded row keeps its source.
    assert [(c.source_upload_id, c.source_row) for c in loaded] == [
        (summary.upload_id, 2), (summary.upload_id, 3),
    ]  # fmt: skip
    assert loaded[0].source_payload == {"customer_id": "C1", "name": "Acme", "country": "gb"}

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "UPLOAD_PROCESSED"))
    assert audit is not None and audit.after is not None
    assert audit.after["accepted_rows"] == 2 and audit.entity_id == str(summary.upload_id)


@pytest.mark.parametrize(
    ("body", "status", "accepted", "rejected"),
    [("C1,Acme,GB\nC2,Beta,US", "ACCEPTED", 2, 0), ("C1,Acme,GBR\nC2,,US", "REJECTED", 0, 2)],
)
def test_all_good_or_all_bad(
    db: Session, user_id: int, body: str, status: str, accepted: int, rejected: int
) -> None:
    seeded(db, "202601")
    (summary,) = upload(db, user_id, customers=body)
    assert (summary.status, summary.accepted_rows, summary.rejected_rows) == (
        status, accepted, rejected,
    )  # fmt: skip


def test_bad_headers_reject_one_file_and_the_others_still_load(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    bad, good = upload(
        db,
        user_id,
        customers=b"customer_id,name\nC1,Acme\n",
        products="P1,Sub,,100.00,FIXED,90.00,,RATABLE_DAILY,Y,4100,",
    )
    assert (bad.status, bad.total_rows) == ("REJECTED", 0)
    assert errors(db, bad.upload_id) == [(1, None, "E011")]
    assert good.status == "ACCEPTED"
    product = db.scalar(select(Product).where(Product.product_code == "P1"))
    assert product is not None and product.source_upload_id == good.upload_id
    rule = db.scalar(select(SspRule).where(SspRule.product_id == product.id))
    assert rule is not None
    assert (rule.ssp_source, rule.ssp_value, rule.valid_from) == (
        "FIXED", Decimal("90.00"), date(1900, 1, 1),
    )  # fmt: skip


def test_contract_quarantine_in_the_database(db: Session, user_id: int) -> None:
    """D9: the contract with a bad line is not loaded at all; the other one is."""
    seeded(db, "202601")
    upload(db, user_id, products="SUB,Sub,,100.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,")
    upload(db, user_id, customers="C1,Acme,GB")
    contracts, lines = upload(
        db,
        user_id,
        contracts="K1,C1,2026-01-01,2026-12-31,NEW,2026-01-01\n"
        "K2,C1,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K1,1,SUB,1,1200.00,,2026-01-01,2026-12-31,\n"
        "K2,1,SUB,2,600.00,0.50,2026-01-01,2026-12-31,\n"
        "K2,2,SUB,1,10.00,,2026-01-15,2026-12-31,",  # E012: monthly from the 15th
    )
    assert (contracts.status, contracts.accepted_rows, contracts.rejected_rows) == ("PARTIAL", 1, 1)
    assert (lines.status, lines.accepted_rows, lines.rejected_rows) == ("PARTIAL", 1, 2)
    assert errors(db, contracts.upload_id) == [(3, "contract_id", "E013")]
    assert errors(db, lines.upload_id) == [(3, "contract_id", "E013"), (4, "service_start", "E012")]

    assert db.scalars(select(Contract.contract_code)).all() == ["K1"]
    version = db.scalar(select(ContractVersion))
    assert version is not None
    assert (version.version_no, version.transaction_price, version.booked_period) == (
        1, Decimal("1200.00"), "202601",
    )  # fmt: skip
    assert version.source_upload_id == contracts.upload_id and version.source_row == 2


def test_net_price_rounds_half_up(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    upload(db, user_id, products="D,Daily,,1.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,")
    upload(db, user_id, customers="C1,Acme,GB")
    upload(
        db,
        user_id,
        contracts="K1,C1,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K1,1,D,1.5,0.33,,2026-01-01,2026-12-31,",  # 0.495 -> 0.50
    )
    line = db.scalar(select(ContractLine))
    assert line is not None and line.net_price == Decimal("0.50")
    version = db.scalar(select(ContractVersion))
    assert version is not None and version.transaction_price == Decimal("0.50")


def test_events_create_new_versions(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    upload(
        db,
        user_id,
        products="SUB,Sub,,100.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,\n"
        "PRINT,Print,,50.00,LIST_PRICE,,,POINT_IN_TIME,Y,4200,",
        customers="C1,Acme,GB",
    )
    upload(
        db,
        user_id,
        contracts="K1,C1,2026-01-01,2026-12-31,NEW,2026-01-01",
        contract_lines="K1,1,SUB,1,1200.00,,2026-01-01,2026-12-31,",
    )
    (summary_up, summary_lines) = upload(
        db,
        user_id,
        contracts="K1,C1,2026-01-01,2026-12-31,UPGRADE,2026-07-01",
        contract_lines="K1,2,PRINT,1,300.00,,2026-07-01,2026-12-31,2026-09-30",
    )
    assert summary_up.status == summary_lines.status == "ACCEPTED"
    # An invoice and a delivery can use both the continuing line 1 and the added line 2.
    inv, dlv = upload(
        db,
        user_id,
        invoices="INV-1,K1,2026-07-01,1,600.00\nINV-1,K1,2026-07-01,2,300.00",
        deliveries="DLV-1,K1,2,2026-08-31,0.5",
    )
    assert inv.status == dlv.status == "ACCEPTED", (
        errors(db, inv.upload_id),
        errors(db, dlv.upload_id),
    )
    (cancel,) = upload(db, user_id, contracts="K1,C1,2026-01-01,2026-12-31,CANCELLATION,2026-10-31")
    assert cancel.status == "ACCEPTED", errors(db, cancel.upload_id)

    contract = db.scalar(select(Contract))
    assert contract is not None
    assert (contract.current_version_no, contract.status) == (3, "CANCELLED")
    versions = db.execute(
        select(
            ContractVersion.version_no,
            ContractVersion.event_type,
            ContractVersion.transaction_price,
        ).order_by(ContractVersion.version_no)
    ).all()  # fmt: skip
    assert [tuple(v) for v in versions] == [
        (1, "NEW", Decimal("1200.00")),
        (2, "UPGRADE", Decimal("300.00")),  # TP of the added lines (§5.5)
        (3, "CANCELLATION", Decimal("0")),
    ]
    invoice = db.scalar(select(Invoice))
    assert invoice is not None and invoice.total_amount == Decimal("900.00")
    linked = db.execute(
        select(InvoiceLine.line_no, ContractVersion.version_no)
        .join(ContractLine, ContractLine.id == InvoiceLine.contract_line_id)
        .join(ContractVersion, ContractVersion.id == ContractLine.contract_version_id)
        .order_by(InvoiceLine.line_no)
    ).all()
    assert [tuple(r) for r in linked] == [(1, 1), (2, 2)]  # each line found in its own version


def test_uploads_are_blocked_while_no_period_is_open(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    db.execute(
        update(AccountingPeriod)
        .where(AccountingPeriod.period_key == "202601")
        .values(status=PeriodStatus.CLOSING)
    )
    (summary,) = upload(db, user_id, customers="C1,Acme,GB")
    assert summary.status == "REJECTED"
    assert errors(db, summary.upload_id) == [(1, None, "E009")]
    assert count(db, Customer) == 0


def test_one_file_per_template_per_upload(db: Session, user_id: int) -> None:
    seeded(db, "202601")
    first, second = upload(db, user_id, customers="C1,Acme,GB", customers_="C2,Beta,GB")
    assert first.status == "ACCEPTED"
    assert second.status == "REJECTED" and errors(db, second.upload_id) == [(1, None, "E011")]


# --------------------------------------------------------------------------- the X02 workbook


def test_x02_workbook_loads_month_by_month_without_errors(db: Session, user_id: int) -> None:
    seeded(db, "202501")
    case = REPO / "benchmarks" / "cases" / "X02_revrec_mock_data" / "inputs"
    order = list(TEMPLATES)
    for month in sorted(p for p in case.iterdir() if p.is_dir()):
        files = sorted(month.glob("*.csv"), key=lambda p: order.index(UploadTemplate(p.stem)))
        summaries = upload(db, user_id, **{p.stem: p.read_bytes() for p in files})
        bad = [
            (s.template, errors(db, s.upload_id)[:3]) for s in summaries if s.status != "ACCEPTED"
        ]
        assert bad == [], f"{month.name}: {bad}"

    # Plan P0-T5: X02 = 60 lines, 22 deliveries, 20 invoices.
    assert count(db, ContractLine) == 60
    assert count(db, Delivery) == 22
    assert count(db, Invoice) == 20
    assert (count(db, Customer), count(db, Contract), count(db, Product)) == (20, 20, 36)
    assert db.scalar(select(func.count()).where(InvoiceLine.contract_line_id.is_(None))) == 0
    line = db.scalar(select(ContractLine).where(ContractLine.source_row == 2))
    assert line is not None and line.source_payload is not None
    assert line.source_payload["contract_id"].startswith("00")  # leading zeros survive the database
