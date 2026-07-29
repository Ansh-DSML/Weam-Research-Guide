"""Pure database access for companies. No HTTP/FastAPI imports here on purpose —
this module is unit-tested directly against a real Postgres schema, with no server running.

Concurrency note: two overlapping edits to the same company are resolved last-write-wins,
identical to today's localStorage behavior (no regression). `updated_at` is bumped by the
DB on every write, which leaves room for a future optimistic-lock upgrade without a schema change.

Sensitive-content note: notes/buckets/meta text is never passed to the logger, only ids,
names, and counts — those fields may contain confidential research findings.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import Company

logger = get_logger("app.crud")


class NotFoundError(Exception):
    def __init__(self, company_id: int):
        self.company_id = company_id
        super().__init__(f"company {company_id} not found")


class DuplicateNameError(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"company name '{name}' already exists")


def _normalize_name(name: str) -> str:
    return name.strip()


def get_company(session: Session, company_id: int) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError(company_id)
    return company


def get_company_by_name(session: Session, name: str) -> Company | None:
    stmt = select(Company).where(Company.name == _normalize_name(name))
    return session.execute(stmt).scalar_one_or_none()


def list_companies(session: Session) -> list[Company]:
    stmt = select(Company).order_by(Company.updated_at.desc())
    return list(session.execute(stmt).scalars().all())


def create_company(
    session: Session,
    name: str,
    meta: dict | None = None,
    checks: dict | None = None,
    notes: dict | None = None,
    buckets: dict | None = None,
    dm: dict | None = None,
) -> Company:
    normalized = _normalize_name(name)
    if get_company_by_name(session, normalized) is not None:
        logger.warning("create_company_duplicate", extra={"company_name": normalized, "op": "create"})
        raise DuplicateNameError(normalized)

    company = Company(
        name=normalized,
        meta=meta or {},
        checks=checks or {},
        notes=notes or {},
        buckets=buckets or {},
        dm=dm or {},
    )
    session.add(company)
    session.commit()
    session.refresh(company)
    logger.info("company_created", extra={"company_id": company.id, "company_name": company.name, "op": "create"})
    return company


def update_company(
    session: Session,
    company_id: int,
    meta: dict,
    checks: dict,
    notes: dict,
    buckets: dict,
    dm: dict,
) -> Company:
    company = get_company(session, company_id)
    company.meta = meta
    company.checks = checks
    company.notes = notes
    company.buckets = buckets
    company.dm = dm
    session.commit()
    session.refresh(company)
    logger.info(
        "company_updated",
        extra={
            "company_id": company.id,
            "company_name": company.name,
            "op": "update",
            "checks_count": len(checks or {}),
            "bucket_paths_count": len(buckets or {}),
        },
    )
    return company


def rename_company(session: Session, company_id: int, new_name: str) -> Company:
    company = get_company(session, company_id)
    normalized = _normalize_name(new_name)

    existing = get_company_by_name(session, normalized)
    if existing is not None and existing.id != company_id:
        logger.warning(
            "rename_company_duplicate",
            extra={"company_id": company_id, "attempted_name": normalized, "op": "rename"},
        )
        raise DuplicateNameError(normalized)

    old_name = company.name
    company.name = normalized
    session.commit()
    session.refresh(company)
    logger.info(
        "company_renamed",
        extra={"company_id": company.id, "old_name": old_name, "new_name": company.name, "op": "rename"},
    )
    return company
