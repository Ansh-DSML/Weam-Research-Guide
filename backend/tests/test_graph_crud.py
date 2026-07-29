import pytest

from app import crud, graph_crud


@pytest.fixture()
def company(db_session):
    return crud.create_company(db_session, name="Graph CRUD Co")


def test_upsert_node_creates_then_updates_not_duplicates(db_session, company):
    n1 = graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", attrs={"title": "CEO"})
    n2 = graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", attrs={"title": "CEO"})
    assert n1.id == n2.id  # same row, not a duplicate

    graph = graph_crud.get_graph(db_session, company.id)
    person_nodes = [n for n in graph["nodes"] if n.type == "Person" and n.name == "Jane Doe"]
    assert len(person_nodes) == 1


def test_upsert_node_merges_attrs_not_overwrites(db_session, company):
    graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", attrs={"title": "CEO"})
    updated = graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", attrs={"tenure": "5 years"})
    assert updated.attrs == {"title": "CEO", "tenure": "5 years"}  # merged, not replaced


def test_upsert_node_source_refs_accumulate_without_duplicates(db_session, company):
    ref_a = {"field": "notes.ops", "tag": "Fact"}
    ref_b = {"field": "notes.growth", "tag": "Hypothesis"}
    graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", source_refs=[ref_a])
    updated = graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe", source_refs=[ref_a, ref_b])
    assert updated.source_refs == [ref_a, ref_b]  # no duplicate of ref_a


def test_upsert_edge_creates_then_updates_not_duplicates(db_session, company):
    a = graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe")
    b = graph_crud.upsert_node(db_session, company.id, "Company", "Graph CRUD Co")
    e1 = graph_crud.upsert_edge(db_session, company.id, a.id, b.id, "WORKS_AT")
    e2 = graph_crud.upsert_edge(db_session, company.id, a.id, b.id, "WORKS_AT")
    assert e1.id == e2.id

    graph = graph_crud.get_graph(db_session, company.id)
    assert len(graph["edges"]) == 1


def test_ensure_company_node_idempotent(db_session, company):
    n1 = graph_crud.ensure_company_node(db_session, company.id, company.name)
    n2 = graph_crud.ensure_company_node(db_session, company.id, company.name)
    assert n1.id == n2.id
    assert n1.type == graph_crud.COMPANY_NODE_TYPE


def test_ensure_company_node_renames_in_place_not_duplicated(db_session, company):
    original = graph_crud.ensure_company_node(db_session, company.id, company.name)
    renamed = graph_crud.ensure_company_node(db_session, company.id, "Graph CRUD Co Renamed")
    assert renamed.id == original.id  # same row, renamed — not a second Company node
    assert renamed.name == "Graph CRUD Co Renamed"

    graph = graph_crud.get_graph(db_session, company.id)
    company_nodes = [n for n in graph["nodes"] if n.type == graph_crud.COMPANY_NODE_TYPE]
    assert len(company_nodes) == 1


def test_get_graph_empty_for_company_with_no_graph_data(db_session, company):
    graph = graph_crud.get_graph(db_session, company.id)
    assert graph == {"nodes": [], "edges": []}


def test_get_graph_scoped_to_company_not_leaking_across_companies(db_session, company):
    other = crud.create_company(db_session, name="Other Graph Co")
    graph_crud.upsert_node(db_session, company.id, "Person", "Jane Doe")
    graph_crud.upsert_node(db_session, other.id, "Person", "John Smith")

    graph = graph_crud.get_graph(db_session, company.id)
    names = [n.name for n in graph["nodes"]]
    assert names == ["Jane Doe"]
    assert "John Smith" not in names
