"""Pure database access for the knowledge graph (nodes/edges). No HTTP imports here —
mirrors crud.py's pattern: unit-tested directly against a real Postgres schema.

Merge semantics: upsert_node/upsert_edge are idempotent on (company_id, type, name) and
(company_id, src_id, dst_id, rel_type) respectively — re-running extraction on unchanged or
overlapping data updates existing rows (merges attrs, appends new source_refs) rather than
duplicating. This is what makes the graph "grow" safely across repeated saves.

Sensitive-content note: entity/relation *names* can originate from confidential research
notes, so — same rule as crud.py — logs here carry only ids/types/counts, never name values.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import Edge, Node

logger = get_logger("app.graph_crud")

COMPANY_NODE_TYPE = "Company"


def _merge_source_refs(existing: list, new: list) -> list:
    merged = list(existing)
    for ref in new:
        if ref not in merged:
            merged.append(ref)
    return merged


def upsert_node(
    session: Session,
    company_id: int,
    type_: str,
    name: str,
    attrs: dict | None = None,
    source_refs: list | None = None,
) -> Node:
    stmt = select(Node).where(Node.company_id == company_id, Node.type == type_, Node.name == name)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing is not None:
        if attrs:
            existing.attrs = {**existing.attrs, **attrs}
        if source_refs:
            existing.source_refs = _merge_source_refs(existing.source_refs, source_refs)
        session.commit()
        session.refresh(existing)
        logger.info("node_upserted", extra={"company_id": company_id, "node_type": type_, "was_new": False})
        return existing

    node = Node(company_id=company_id, type=type_, name=name, attrs=attrs or {}, source_refs=source_refs or [])
    session.add(node)
    session.commit()
    session.refresh(node)
    logger.info("node_upserted", extra={"company_id": company_id, "node_type": type_, "was_new": True})
    return node


def find_edge(session: Session, company_id: int, src_id: int, dst_id: int, rel_type: str) -> Edge | None:
    stmt = select(Edge).where(
        Edge.company_id == company_id,
        Edge.src_id == src_id,
        Edge.dst_id == dst_id,
        Edge.rel_type == rel_type,
    )
    return session.execute(stmt).scalar_one_or_none()


def upsert_edge(
    session: Session,
    company_id: int,
    src_id: int,
    dst_id: int,
    rel_type: str,
    attrs: dict | None = None,
    source_refs: list | None = None,
) -> Edge:
    existing = find_edge(session, company_id, src_id, dst_id, rel_type)

    if existing is not None:
        if attrs:
            existing.attrs = {**existing.attrs, **attrs}
        if source_refs:
            existing.source_refs = _merge_source_refs(existing.source_refs, source_refs)
        session.commit()
        session.refresh(existing)
        logger.info("edge_upserted", extra={"company_id": company_id, "rel_type": rel_type, "was_new": False})
        return existing

    edge = Edge(
        company_id=company_id,
        src_id=src_id,
        dst_id=dst_id,
        rel_type=rel_type,
        attrs=attrs or {},
        source_refs=source_refs or [],
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    logger.info("edge_upserted", extra={"company_id": company_id, "rel_type": rel_type, "was_new": True})
    return edge


def ensure_company_node(session: Session, company_id: int, company_name: str) -> Node:
    """There is exactly one Company-type node per company_id, for its whole lifetime — keyed
    on company_id alone, NOT on (company_id, type, name) like every other node. If it were
    keyed on name too, renaming a company would silently create a second, stale Company node
    under the old name instead of renaming the existing one."""
    stmt = select(Node).where(Node.company_id == company_id, Node.type == COMPANY_NODE_TYPE)
    existing = session.execute(stmt).scalar_one_or_none()
    if existing is not None:
        if existing.name != company_name:
            existing.name = company_name
            session.commit()
            session.refresh(existing)
        return existing
    return upsert_node(session, company_id, COMPANY_NODE_TYPE, company_name)


def get_graph(session: Session, company_id: int) -> dict:
    nodes = session.execute(select(Node).where(Node.company_id == company_id)).scalars().all()
    edges = session.execute(select(Edge).where(Edge.company_id == company_id)).scalars().all()
    return {"nodes": list(nodes), "edges": list(edges)}
