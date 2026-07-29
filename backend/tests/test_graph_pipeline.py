from sqlalchemy.orm import sessionmaker

from app import crud, graph_crud, graph_pipeline
from app.extraction.base import ExtractionResult
from app.extraction.fake_extractor import FakeExtractor


class CountingExtractor:
    """Wraps FakeExtractor and counts calls, so tests can assert the hash-guard actually
    skipped re-invoking the (potentially paid) extractor."""

    def __init__(self):
        self._inner = FakeExtractor()
        self.call_count = 0

    def extract(self, text: str) -> ExtractionResult:
        self.call_count += 1
        return self._inner.extract(text)


class RaisingExtractor:
    def extract(self, text: str) -> ExtractionResult:
        raise RuntimeError("simulated extractor failure")


def _session_factory_for(test_engine):
    return sessionmaker(bind=test_engine)


def test_first_save_populates_graph_and_stores_hash(db_session, test_engine):
    company = crud.create_company(
        db_session,
        name="Pipeline Co",
        meta={"category": "Plumbing"},
        notes={"ops": "Jane Doe leads the ops team."},
    )
    extractor = CountingExtractor()

    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=_session_factory_for(test_engine))

    graph = graph_crud.get_graph(db_session, company.id)
    node_names = {n.name for n in graph["nodes"]}
    assert "Pipeline Co" in node_names  # Company node
    assert "Plumbing" in node_names  # from the mapper
    assert "Jane Doe" in node_names  # from the (fake) text extractor
    assert extractor.call_count == 1

    db_session.expire_all()  # the pipeline committed via its own session — force a fresh read
    reloaded = crud.get_company(db_session, company.id)
    assert reloaded.last_extracted_text_hash is not None


def test_identical_resave_skips_text_extractor_but_mapper_still_runs(db_session, test_engine):
    company = crud.create_company(
        db_session, name="Pipeline Skip Co", meta={"category": "Plumbing"}, notes={"ops": "Jane Doe leads ops."}
    )
    extractor = CountingExtractor()
    factory = _session_factory_for(test_engine)

    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)
    assert extractor.call_count == 1

    # re-run with identical data — text extractor must NOT be invoked again
    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)
    assert extractor.call_count == 1  # unchanged — the hash guard skipped it

    # mapper-derived nodes must still be present and not duplicated
    graph = graph_crud.get_graph(db_session, company.id)
    plumbing_nodes = [n for n in graph["nodes"] if n.name == "Plumbing"]
    assert len(plumbing_nodes) == 1


def test_edited_notes_retrigger_extraction_and_grow_the_graph_without_losing_old_nodes(db_session, test_engine):
    company = crud.create_company(db_session, name="Pipeline Grow Co", notes={"ops": "Jane Doe leads ops."})
    extractor = CountingExtractor()
    factory = _session_factory_for(test_engine)

    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)
    graph_after_first = graph_crud.get_graph(db_session, company.id)
    names_after_first = {n.name for n in graph_after_first["nodes"]}
    assert "Jane Doe" in names_after_first

    # edit: add more free text mentioning a new person, keep the old sentence too
    crud.update_company(
        db_session,
        company.id,
        meta={},
        checks={},
        notes={"ops": "Jane Doe leads ops. John Smith joined as CFO."},
        buckets={},
        dm={},
    )
    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)
    assert extractor.call_count == 2  # text changed -> re-invoked

    graph_after_second = graph_crud.get_graph(db_session, company.id)
    names_after_second = {n.name for n in graph_after_second["nodes"]}
    assert "Jane Doe" in names_after_second  # old node untouched, not lost
    assert "John Smith" in names_after_second  # new node appended

    jane_nodes = [n for n in graph_after_second["nodes"] if n.name == "Jane Doe"]
    assert len(jane_nodes) == 1  # not duplicated across the two runs


def test_pipeline_survives_extractor_raising(db_session, test_engine):
    company = crud.create_company(db_session, name="Pipeline Fail Co", notes={"ops": "some text"})
    factory = _session_factory_for(test_engine)

    # must not raise out of run_graph_extraction — failure is caught and logged internally
    graph_pipeline.run_graph_extraction(company.id, RaisingExtractor(), session_factory=factory)

    # the company row itself must be completely unaffected by the extraction failure
    reloaded = crud.get_company(db_session, company.id)
    assert reloaded.name == "Pipeline Fail Co"


def test_same_name_from_mapper_and_text_extractor_resolves_to_one_node(db_session, test_engine):
    # dm.name establishes a Person node; the free text separately mentions the same name —
    # the fake extractor's regex would propose it again as an "Other" node. Must resolve to
    # the same existing node, not create a second one that only differs by type.
    company = crud.create_company(
        db_session,
        name="Entity Resolution Co",
        dm={"name": "Jane Doe"},
        notes={"ops": "Jane Doe also works with John Smith on this account."},
    )
    factory = _session_factory_for(test_engine)
    graph_pipeline.run_graph_extraction(company.id, CountingExtractor(), session_factory=factory)

    graph = graph_crud.get_graph(db_session, company.id)
    jane_nodes = [n for n in graph["nodes"] if n.name == "Jane Doe"]
    assert len(jane_nodes) == 1
    assert jane_nodes[0].type == "Person"  # the mapper's more specific type wins over "Other"


def test_pipeline_on_deleted_company_is_a_silent_noop(db_session, test_engine):
    factory = _session_factory_for(test_engine)
    # id 999999 doesn't exist — must not raise
    graph_pipeline.run_graph_extraction(999999, CountingExtractor(), session_factory=factory)


def test_entity_from_a_tagged_bucket_finding_carries_the_tag(db_session, test_engine):
    company = crud.create_company(
        db_session,
        name="Tagged Findings Co",
        buckets={"gaps": [{"tag": "FACT", "text": "Jane Doe leads the ops team.", "source": ""}]},
    )
    factory = _session_factory_for(test_engine)

    graph_pipeline.run_graph_extraction(company.id, CountingExtractor(), session_factory=factory)

    graph = graph_crud.get_graph(db_session, company.id)
    jane = next(n for n in graph["nodes"] if n.name == "Jane Doe")
    assert jane.attrs["finding_tags"] == ["FACT"]

    mentions = next(
        e for e in graph["edges"] if e.rel_type == "MENTIONS" and e.src_id == jane.id
    )
    assert mentions.attrs["finding_tags"] == ["FACT"]


def test_entity_mentioned_in_two_differently_tagged_findings_gets_both_tags(db_session, test_engine):
    company = crud.create_company(
        db_session,
        name="Multi Tag Co",
        buckets={
            "gaps": [
                {"tag": "FACT", "text": "Jane Doe leads the ops team.", "source": ""},
                {"tag": "HYPOTHESIS", "text": "Jane Doe may also own vendor selection.", "source": ""},
            ]
        },
    )
    factory = _session_factory_for(test_engine)

    graph_pipeline.run_graph_extraction(company.id, CountingExtractor(), session_factory=factory)

    graph = graph_crud.get_graph(db_session, company.id)
    jane = next(n for n in graph["nodes"] if n.name == "Jane Doe")
    assert jane.attrs["finding_tags"] == ["FACT", "HYPOTHESIS"]


def test_finding_tags_accumulate_across_saves_instead_of_being_overwritten(db_session, test_engine):
    company = crud.create_company(
        db_session,
        name="Accumulating Tags Co",
        buckets={"gaps": [{"tag": "FACT", "text": "Jane Doe leads the ops team.", "source": ""}]},
    )
    factory = _session_factory_for(test_engine)
    extractor = CountingExtractor()
    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)

    crud.update_company(
        db_session,
        company.id,
        meta={},
        checks={},
        notes={},
        buckets={
            "gaps": [
                {"tag": "FACT", "text": "Jane Doe leads the ops team.", "source": ""},
                {"tag": "ASSUMPTION", "text": "Jane Doe might expand the team next quarter.", "source": ""},
            ]
        },
        dm={},
    )
    graph_pipeline.run_graph_extraction(company.id, extractor, session_factory=factory)
    assert extractor.call_count == 2  # bucket text changed -> re-invoked

    graph = graph_crud.get_graph(db_session, company.id)
    jane_nodes = [n for n in graph["nodes"] if n.name == "Jane Doe"]
    assert len(jane_nodes) == 1  # still not duplicated
    assert jane_nodes[0].attrs["finding_tags"] == ["ASSUMPTION", "FACT"]


def test_untagged_free_text_entity_gets_no_finding_tags(db_session, test_engine):
    company = crud.create_company(db_session, name="Untagged Co", notes={"ops": "Jane Doe leads ops."})
    factory = _session_factory_for(test_engine)

    graph_pipeline.run_graph_extraction(company.id, CountingExtractor(), session_factory=factory)

    graph = graph_crud.get_graph(db_session, company.id)
    jane = next(n for n in graph["nodes"] if n.name == "Jane Doe")
    assert "finding_tags" not in jane.attrs
