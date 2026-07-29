"""Orchestrates graph extraction for a single company: always runs the free structured-field
mapper, conditionally runs the (possibly paid) text extractor, and upserts everything via
graph_crud. Opens its own DB session — this runs from a FastAPI BackgroundTask, after the
request's own session may already be closed.

Failure isolation: any exception here is caught and logged. The company save that triggered
this has already committed by the time this runs — a failure here must never look like a
failed save to the user, and must never be mistaken for one in the logs either.

Cost control: the text extractor only runs when the free-text fields actually changed since
the last successful extraction (a sha256 fingerprint stored on the company row) — a checkbox
toggle or a rename must not burn a Groq API call.
"""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud, graph_crud, graph_mapper
from app.db import SessionLocal
from app.extraction.base import Extractor
from app.logging_config import get_logger
from app.models import Edge, Node

logger = get_logger("app.graph_pipeline")

EXTRACTED_SOURCE_REF = [{"origin": "text_extraction"}]


def get_default_session_factory():
    """A dependency, not a plain default — so tests can override it (via
    app.dependency_overrides, exactly like get_session) to point background tasks at the
    disposable test schema instead of the real dev database."""
    return SessionLocal


def get_default_extractor() -> Extractor:
    from app.config import settings

    keys = settings.groq_api_keys_list
    if keys:
        from app.extraction.groq_extractor import GroqExtractor

        return GroqExtractor(api_keys=keys, model=settings.groq_model)
    from app.extraction.null_extractor import NullExtractor

    return NullExtractor()


def _collect_tagged_entries(company) -> list[tuple[str, str | None]]:
    """(text, tag) pairs across every free-text source. Bucket entries carry a
    FACT/ASSUMPTION/HYPOTHESIS tag (the console's finding-classification field); meta.notes and
    the notes dict don't, so their tag is None."""
    entries: list[tuple[str, str | None]] = []
    notes_text = company.meta.get("notes", "")
    if notes_text:
        entries.append((notes_text, None))
    for text in company.notes.values():
        if text:
            entries.append((text, None))
    for bucket_entries in company.buckets.values():
        for entry in bucket_entries:
            if isinstance(entry, dict) and entry.get("text"):
                entries.append((entry["text"], entry.get("tag")))
    return entries


def _tags_mentioning(tagged_entries: list[tuple[str, str | None]], *names: str) -> list[str]:
    """Which FACT/ASSUMPTION/HYPOTHESIS tags come from an entry whose text contains every
    given name. Heuristic substring match — good enough to surface provenance, not a claim of
    precise span-level attribution."""
    return sorted({tag for text, tag in tagged_entries if tag and all(name in text for name in names)})


def _merged_finding_tags(existing: Node | Edge | None, new_tags: list[str]) -> dict | None:
    """graph_crud's upsert does a shallow dict merge on attrs, which would let a fresh
    finding_tags list silently overwrite tags recorded on an earlier save. Union with whatever
    is already stored so a node's/edge's tag history only grows, same as the rest of the graph."""
    if not new_tags:
        return None
    prior = set((existing.attrs or {}).get("finding_tags", [])) if existing else set()
    return {"finding_tags": sorted(prior | set(new_tags))}


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_node_id_by_name(session: Session, company_id: int, name: str) -> int | None:
    node = session.execute(
        select(Node).where(Node.company_id == company_id, Node.name == name)
    ).scalars().first()
    return node.id if node else None


def _apply_structured_specs(session: Session, company_id: int, company_node, node_specs, edge_specs) -> int:
    ref_to_id = {(company_node.type, company_node.name): company_node.id}
    touched = 0
    for spec in node_specs:
        node = graph_crud.upsert_node(session, company_id, spec.type, spec.name, attrs=spec.attrs)
        ref_to_id[(spec.type, spec.name)] = node.id
        touched += 1
    for spec in edge_specs:
        src_id = ref_to_id.get(spec.src)
        dst_id = ref_to_id.get(spec.dst)
        if src_id is None or dst_id is None:
            continue  # shouldn't happen given how specs are built — never crash the pipeline over it
        graph_crud.upsert_edge(session, company_id, src_id, dst_id, spec.rel_type, attrs=spec.attrs)
        touched += 1
    return touched


def _apply_text_extraction(
    session: Session,
    company,
    company_node,
    extractor: Extractor,
    tagged_entries: list[tuple[str, str | None]],
) -> int:
    combined_text = "\n".join(text for text, _tag in tagged_entries)
    result = extractor.extract(combined_text)

    touched = 0
    name_to_id: dict[str, int] = {}
    for entity in result.entities:
        # If a node with this exact name already exists (typically from graph_mapper — e.g.
        # the decision-maker's name is already a Person node), resolve to its EXISTING type
        # rather than the extractor's guessed type. Otherwise "Jane Doe" ends up as two nodes:
        # Person/Jane Doe (structured) and Other/Jane Doe (text-extracted) — a duplicate that
        # only differs by type, which upsert_node's (company_id, type, name) key can't catch.
        existing_id = _find_node_id_by_name(session, company.id, entity.name)
        existing_node = session.get(Node, existing_id) if existing_id is not None else None
        resolved_type = existing_node.type if existing_node is not None else entity.type
        attrs = _merged_finding_tags(existing_node, _tags_mentioning(tagged_entries, entity.name))
        node = graph_crud.upsert_node(
            session, company.id, resolved_type, entity.name, attrs=attrs, source_refs=EXTRACTED_SOURCE_REF
        )
        name_to_id[entity.name] = node.id
        touched += 1
        # link every extracted entity back to the company so nothing is an orphaned island;
        # carry the same finding_tags so "what did we learn from Hypotheses" can query MENTIONS too
        graph_crud.upsert_edge(
            session, company.id, node.id, company_node.id, "MENTIONS", attrs=attrs, source_refs=EXTRACTED_SOURCE_REF
        )
        touched += 1

    for relation in result.relations:
        src_id = name_to_id.get(relation.source) or _find_node_id_by_name(session, company.id, relation.source)
        dst_id = name_to_id.get(relation.target) or _find_node_id_by_name(session, company.id, relation.target)
        if src_id is None or dst_id is None:
            continue
        existing_edge = graph_crud.find_edge(session, company.id, src_id, dst_id, relation.rel_type)
        edge_attrs = _merged_finding_tags(
            existing_edge, _tags_mentioning(tagged_entries, relation.source, relation.target)
        )
        graph_crud.upsert_edge(
            session, company.id, src_id, dst_id, relation.rel_type, attrs=edge_attrs, source_refs=EXTRACTED_SOURCE_REF
        )
        touched += 1

    return touched


def run_graph_extraction(company_id: int, extractor: Extractor, session_factory=None) -> None:
    """`session_factory` defaults to the app's real `SessionLocal` (bound to `DATABASE_URL`).
    Tests inject a factory bound to the disposable test schema instead, so this never touches
    the real dev database."""
    session_factory = session_factory or SessionLocal
    session = session_factory()
    try:
        try:
            company = crud.get_company(session, company_id)
        except crud.NotFoundError:
            return  # deleted/renamed away before this background task ran — nothing to do

        company_node = graph_crud.ensure_company_node(session, company.id, company.name)

        node_specs, edge_specs = graph_mapper.map_structured_fields(
            company.name, company.meta, company.dm, company.checks
        )
        mapper_touched = _apply_structured_specs(session, company.id, company_node, node_specs, edge_specs)

        tagged_entries = _collect_tagged_entries(company)
        combined_text = "\n".join(text for text, _tag in tagged_entries)
        text_hash = _fingerprint(combined_text)
        skipped = text_hash == company.last_extracted_text_hash

        extractor_touched = 0
        if not skipped:
            extractor_touched = _apply_text_extraction(session, company, company_node, extractor, tagged_entries)
            company.last_extracted_text_hash = text_hash
            session.commit()

        logger.info(
            "graph_extraction_completed",
            extra={
                "company_id": company.id,
                "mapper_touched": mapper_touched,
                "text_extraction_skipped": skipped,
                "text_extraction_touched": extractor_touched,
            },
        )
    except Exception:
        logger.error("graph_extraction_failed", extra={"company_id": company_id}, exc_info=True)
    finally:
        session.close()
