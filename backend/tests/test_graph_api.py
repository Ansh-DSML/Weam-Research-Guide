def test_graph_endpoint_has_only_company_node_for_fresh_company(api_client):
    # Creating a company now auto-triggers the graph pipeline (T2.7), so a fresh company
    # immediately has exactly its own Company node — not an empty graph, and not yet any
    # entities derived from data that doesn't exist.
    created = api_client.post("/api/companies", json={"name": "Graph API Empty Co"}).json()
    resp = api_client.get(f"/api/companies/{created['id']}/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert [n["type"] for n in body["nodes"]] == ["Company"]
    assert body["nodes"][0]["name"] == "Graph API Empty Co"
    assert body["edges"] == []


def test_update_via_api_triggers_extraction_and_graph_reflects_it(api_client):
    created = api_client.post("/api/companies", json={"name": "Graph API Update Co"}).json()
    company_id = created["id"]

    api_client.put(
        f"/api/companies/{company_id}",
        json={
            "meta": {"category": "Plumbing"},
            "checks": {},
            "notes": {"ops": "Jane Doe leads the ops team."},
            "buckets": {},
            "dm": {},
        },
    )

    resp = api_client.get(f"/api/companies/{company_id}/graph")
    names = {n["name"] for n in resp.json()["nodes"]}
    assert "Plumbing" in names  # from graph_mapper, triggered by the PUT
    assert "Jane Doe" in names  # from the fake extractor, triggered by the same PUT


def test_rename_via_api_renames_company_node_not_duplicates_it(api_client):
    created = api_client.post("/api/companies", json={"name": "Graph API Old Name Co"}).json()
    company_id = created["id"]

    api_client.post(f"/api/companies/{company_id}/rename", json={"new_name": "Graph API New Name Co"})

    resp = api_client.get(f"/api/companies/{company_id}/graph")
    company_nodes = [n for n in resp.json()["nodes"] if n["type"] == "Company"]
    assert len(company_nodes) == 1
    assert company_nodes[0]["name"] == "Graph API New Name Co"


def test_graph_endpoint_404_for_unknown_company(api_client):
    resp = api_client.get("/api/companies/999999/graph")
    assert resp.status_code == 404


def test_graph_endpoint_returns_populated_graph_after_manual_seed(api_client, test_engine):
    from sqlalchemy.orm import sessionmaker

    from app import graph_crud

    created = api_client.post("/api/companies", json={"name": "Graph API Seeded Co"}).json()
    company_id = created["id"]

    session_local = sessionmaker(bind=test_engine)
    session = session_local()
    company_node = graph_crud.ensure_company_node(session, company_id, "Graph API Seeded Co")
    person_node = graph_crud.upsert_node(session, company_id, "Person", "Jane Doe")
    graph_crud.upsert_edge(session, company_id, person_node.id, company_node.id, "WORKS_AT")
    session.close()

    resp = api_client.get(f"/api/companies/{company_id}/graph")
    assert resp.status_code == 200
    body = resp.json()
    names = {n["name"] for n in body["nodes"]}
    assert names == {"Graph API Seeded Co", "Jane Doe"}
    assert len(body["edges"]) == 1
    assert body["edges"][0]["rel_type"] == "WORKS_AT"
