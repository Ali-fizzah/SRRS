"""P2-T3 acceptance: upload U01 -> 12 schedule lines, through the real loader (plan §5.2-5.4)."""

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.roles import Role
from app.ingestion.loader import load_upload
from app.ingestion.templates import TEMPLATES
from app.models import (
    AuditLog,
    Contract,
    ContractLine,
    ContractVersion,
    Customer,
    JobRun,
    PerformanceObligation,
    Product,
    RevenueSchedule,
    ScheduleLine,
    SspRule,
    UploadFile,
)
from app.models.enums import JobType, SspSource, UploadTemplate
from app.services.recognition_run import RunSummary, run_recognition
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

SUB = "SUB,Sub,,1200.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,"
DAILY = "DAILY,Daily,,100.00,LIST_PRICE,,,RATABLE_DAILY,Y,4100,"
PRINT = "PRINT,Print,,50.00,LIST_PRICE,,,POINT_IN_TIME,Y,4200,"
SETUP = "SETUP,Setup fee,,500.00,LIST_PRICE,,,POINT_IN_TIME,N,4300,"


@pytest.fixture
def user_id(db: Session) -> int:
    seed.seed_accounts(db)
    seed.seed_periods(db, "202501")
    return make_user(db, [Role.ACCOUNTANT]).id


def upload(db: Session, user_id: int, **files: str) -> None:
    batch = []
    for name, body in files.items():
        template = TEMPLATES[UploadTemplate(name)]
        record = UploadFile(
            template=template.name,
            original_filename=f"{name}.csv",
            sha256="0" * 64,
            stored_path="(test)",
            uploaded_by=user_id,
            period_key="202501",
        )
        db.add(record)
        batch.append((record, (",".join(template.headers) + "\n" + body.strip() + "\n").encode()))
    db.flush()
    summaries = load_upload(db, batch, user_id)
    assert all(s.status == "ACCEPTED" for s in summaries), summaries


def new_contract(
    db: Session, user_id: int, code: str, lines: str, products: str = SUB, customer: str = "C1"
) -> None:
    """Upload one NEW contract for 2025, adding its products and customer if they are new."""
    known = set(db.scalars(select(Product.product_code)))
    rows = [row for row in products.split("\n") if row.split(",")[0] not in known]
    if rows:
        upload(db, user_id, products="\n".join(rows))
    if db.scalar(select(Customer.id).where(Customer.customer_code == customer)) is None:
        upload(db, user_id, customers=f"{customer},Acme,GB")
    upload(
        db,
        user_id,
        contracts=f"{code},{customer},2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines="\n".join(f"{code},{line}" for line in lines.split("\n")),
    )


def amounts(db: Session) -> list[Decimal]:
    return list(db.scalars(select(ScheduleLine.amount).order_by(ScheduleLine.service_period)))


def reasons(summary: RunSummary) -> dict[str, str]:
    return {s.contract_code: s.reason for s in summary.skipped}


# --------------------------------------------------------------------------- acceptance


def test_u01_upload_gives_12_schedule_lines(db: Session, user_id: int) -> None:
    """U01: 1,200.00, 1 Jan to 31 Dec, ratable monthly -> 100.00 x 12."""
    new_contract(db, user_id, "U01", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    summary = run_recognition(db, user_id)
    assert (summary.contracts_generated, summary.obligations_created) == (1, 1)
    assert summary.schedule_lines_created == 12 and summary.skipped == []

    lines = list(db.scalars(select(ScheduleLine).order_by(ScheduleLine.service_period)))
    assert [line.service_period for line in lines] == [f"2025{m:02d}" for m in range(1, 13)]
    assert {line.amount for line in lines} == {Decimal("100.00")}
    # §5.4: all PENDING; the run for 202501 books January and leaves later months alone.
    assert {line.status.value for line in lines} == {"PENDING"}
    assert [line.posting_period for line in lines] == ["202501"] + [None] * 11
    assert {line.is_catch_up for line in lines} == {False}
    assert {line.journal_line_id for line in lines} == {None}

    obligation = db.scalar(select(PerformanceObligation))
    assert obligation is not None
    assert obligation.allocated_amount == Decimal("1200.00")
    assert obligation.ssp_amount == Decimal("1200.00")
    assert obligation.method == "RATABLE_MONTHLY" and obligation.status == "ACTIVE"
    assert (obligation.service_start, obligation.service_end) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )
    schedule = db.scalar(select(RevenueSchedule))
    assert schedule is not None and schedule.status == "ACTIVE"
    assert schedule.performance_obligation_id == obligation.id


def test_b01_subscription_amounts_and_total_equal_the_allocation(db: Session, user_id: int) -> None:
    """The §11.1 pass rule: a PO's schedule total exactly equals its allocation."""
    new_contract(db, user_id, "B01", "1,SUB,1,11200.00,,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    assert amounts(db) == [Decimal("933.33")] * 11 + [Decimal("933.37")]
    assert db.scalar(select(func.sum(ScheduleLine.amount))) == Decimal("11200.00")


def test_every_line_traces_back_to_its_uploaded_row(db: Session, user_id: int) -> None:
    """CLAUDE.md rule 5."""
    new_contract(db, user_id, "000123-U01", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    row = db.execute(
        select(Contract.contract_code, ContractLine.source_row, ContractLine.source_payload)
        .join(ContractVersion, ContractVersion.contract_id == Contract.id)
        .join(ContractLine, ContractLine.contract_version_id == ContractVersion.id)
        .join(PerformanceObligation, PerformanceObligation.contract_line_id == ContractLine.id)
        .join(
            RevenueSchedule, RevenueSchedule.performance_obligation_id == PerformanceObligation.id
        )
        .join(ScheduleLine, ScheduleLine.schedule_id == RevenueSchedule.id)
        .limit(1)
    ).one()
    assert row.contract_code == "000123-U01" and row.source_row == 2
    assert row.source_payload["unit_price"] == "1200.00"


# --------------------------------------------------------------------------- allocation inputs


def test_setup_fee_flows_into_the_single_obligation(db: Session, user_id: int) -> None:
    """D4: the fee adds to TP, gets no obligation, and is spread through the subscription."""
    new_contract(
        db,
        user_id,
        "B03",
        "1,SUB,1,1200.00,,2025-01-01,2025-12-31,\n2,SETUP,1,500.00,,2025-01-01,2025-01-31,",
        products=f"{SUB}\n{SETUP}",
    )
    summary = run_recognition(db, user_id)
    assert summary.obligations_created == 1
    obligation = db.scalar(select(PerformanceObligation))
    assert obligation is not None and obligation.allocated_amount == Decimal("1700.00")
    assert db.scalar(select(func.sum(ScheduleLine.amount))) == Decimal("1700.00")
    version = db.scalar(select(ContractVersion))
    assert version is not None and version.transaction_price == Decimal("1700.00")


def test_discount_reduces_the_allocation_but_not_the_ssp(db: Session, user_id: int) -> None:
    new_contract(db, user_id, "K", "1,SUB,2,1200.00,300.00,2025-01-01,2025-12-31,")
    run_recognition(db, user_id)
    obligation = db.scalar(select(PerformanceObligation))
    assert obligation is not None
    assert obligation.allocated_amount == Decimal("2100.00")
    assert obligation.ssp_amount == Decimal("2400.00")  # list price x quantity


@pytest.mark.parametrize(
    ("product", "quantity", "expected_ssp"),
    [
        ("P,P,,100.00,FIXED,90.25,,RATABLE_MONTHLY,Y,4100,", "2", "180.50"),
        ("P,P,,100.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,", "1.5", "150.00"),
        ("P,P,,33.33,PCT_OF_LIST,,50,RATABLE_MONTHLY,Y,4100,", "1", "16.67"),  # 16.665 rounds up
    ],
    ids=["fixed", "list price", "percent of list"],
)
def test_ssp_comes_from_the_products_rule(
    db: Session, user_id: int, product: str, quantity: str, expected_ssp: str
) -> None:
    new_contract(
        db, user_id, "K", f"1,P,{quantity},100.00,,2025-01-01,2025-12-31,", products=product
    )
    assert run_recognition(db, user_id).skipped == []
    obligation = db.scalar(select(PerformanceObligation))
    assert obligation is not None and obligation.ssp_amount == Decimal(expected_ssp)


def test_ssp_is_looked_up_on_the_effective_date(db: Session, user_id: int) -> None:
    """§5.2: history is kept; the rule in force on the version's effective date applies."""
    new_contract(db, user_id, "K", "1,SUB,1,100.00,,2025-01-01,2025-12-31,")
    product_id = db.scalar(select(Product.id))
    assert product_id is not None
    db.add_all(
        [
            SspRule(
                product_id=product_id,
                ssp_source=SspSource.FIXED,
                ssp_value=Decimal("700.00"),
                valid_from=date(2024, 6, 1),
            ),
            SspRule(  # starts after the contract: must not apply
                product_id=product_id,
                ssp_source=SspSource.FIXED,
                ssp_value=Decimal("999.00"),
                valid_from=date(2025, 6, 1),
            ),
        ]
    )
    db.flush()
    run_recognition(db, user_id)
    obligation = db.scalar(select(PerformanceObligation))
    assert obligation is not None and obligation.ssp_amount == Decimal("700.00")


# --------------------------------------------------------------------------- skipped contracts


def test_bundles_and_every_method_generate_together(db: Session, user_id: int) -> None:
    """P3-T2, P3-T3: relative-SSP allocation across obligations with different methods."""
    products = f"{SUB}\n{DAILY}\n{PRINT}"
    new_contract(
        db,
        user_id,
        "A-BUNDLE",
        "1,SUB,1,1200.00,,2025-01-01,2025-12-31,\n"
        "2,PRINT,1,50.00,,2025-01-01,2025-12-31,2025-03-15\n"
        "3,DAILY,1,100.00,,2025-02-10,2025-04-20,",
        products=products,
    )
    summary = run_recognition(db, user_id)
    assert summary.skipped == []
    assert (summary.contracts_generated, summary.obligations_created) == (1, 3)

    allocated = db.execute(
        select(
            ContractLine.line_no,
            PerformanceObligation.allocated_amount,
            PerformanceObligation.method,
        )
        .join(PerformanceObligation, PerformanceObligation.contract_line_id == ContractLine.id)
        .order_by(ContractLine.line_no)
    ).all()
    # TP = SSP = 1,350.00, so each line keeps its own price.
    assert [(no, amount, method.value) for no, amount, method in allocated] == [
        (1, Decimal("1200.00"), "RATABLE_MONTHLY"),
        (2, Decimal("50.00"), "POINT_IN_TIME"),
        (3, Decimal("100.00"), "RATABLE_DAILY"),
    ]
    assert db.scalar(select(func.sum(ScheduleLine.amount))) == Decimal("1350.00")
    # 12 months + one completion month + February to April
    assert summary.schedule_lines_created == 12 + 1 + 3


def test_one_contract_that_cannot_run_does_not_stop_the_others(db: Session, user_id: int) -> None:
    new_contract(
        db,
        user_id,
        "A-ZERO",
        "1,ZERO,1,100.00,,2025-01-01,2025-12-31,",
        products=f"ZERO,Zero,,10.00,FIXED,0.00,,RATABLE_MONTHLY,Y,4100,\n{SUB}",
    )
    new_contract(db, user_id, "B-OK", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    summary = run_recognition(db, user_id)
    assert reasons(summary) == {"A-ZERO": "NO_SEPARATE_OBLIGATION"}
    assert summary.contracts_generated == 1 and summary.schedule_lines_created == 12
    assert db.scalar(select(func.count()).select_from(PerformanceObligation)) == 1


def test_no_ssp_rule_on_the_effective_date_is_reported(db: Session, user_id: int) -> None:
    upload(db, user_id, products="P,P,,10.00,LIST_PRICE,,,RATABLE_MONTHLY,Y,4100,2025-06-01")
    upload(db, user_id, customers="C1,Acme,GB")
    upload(
        db,
        user_id,
        contracts="K,C1,2025-01-01,2025-12-31,NEW,2025-01-01",
        contract_lines="K,1,P,1,10.00,,2025-01-01,2025-12-31,",
    )
    assert reasons(run_recognition(db, user_id)) == {"K": "NO_SSP_RULE"}


def test_sum_of_ssp_zero_is_reported_as_e014(db: Session, user_id: int) -> None:
    """A separate line whose SSP is 0 passes upload; allocation catches it (§5.2)."""
    new_contract(
        db,
        user_id,
        "K",
        "1,ZERO,1,100.00,,2025-01-01,2025-12-31,",
        products="ZERO,Zero,,10.00,FIXED,0.00,,RATABLE_MONTHLY,Y,4100,",
    )
    summary = run_recognition(db, user_id)
    assert reasons(summary) == {"K": "NO_SEPARATE_OBLIGATION"}
    assert "E014" in summary.skipped[0].message


# --------------------------------------------------------------------------- running it again


def test_running_again_generates_nothing_twice(db: Session, user_id: int) -> None:
    new_contract(db, user_id, "K1", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    assert run_recognition(db, user_id).schedule_lines_created == 12
    again = run_recognition(db, user_id)
    assert (again.contracts_generated, again.schedule_lines_created, again.skipped) == (0, 0, [])
    assert db.scalar(select(func.count()).select_from(ScheduleLine)) == 12

    new_contract(db, user_id, "K2", "1,SUB,1,2400.00,,2025-01-01,2025-12-31,")
    assert run_recognition(db, user_id).contracts_generated == 1  # only the new one
    assert db.scalar(select(func.count()).select_from(ScheduleLine)) == 24


def test_nothing_to_do_is_fine(db: Session, user_id: int) -> None:
    summary = run_recognition(db, user_id)
    assert (summary.contracts_generated, summary.skipped) == (0, [])


def test_the_run_is_audited_and_remembers_its_job(db: Session, user_id: int) -> None:
    new_contract(db, user_id, "K", "1,SUB,1,1200.00,,2025-01-01,2025-12-31,")
    job = JobRun(job_type=JobType.RECOGNITION)
    db.add(job)
    db.flush()
    run_recognition(db, user_id, job.id)

    schedule = db.scalar(select(RevenueSchedule))
    assert schedule is not None and schedule.generated_by_job_id == job.id
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "RECOGNITION_RUN"))
    assert audit is not None and audit.after is not None
    assert audit.user_id == user_id and audit.entity_id == str(job.id)
    assert audit.after["schedule_lines_created"] == 12
