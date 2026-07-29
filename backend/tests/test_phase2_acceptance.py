"""Phase 2 acceptance gate: the concrete "grows over time, even from half info, never
duplicates" scenario, driven entirely through the real HTTP API (the same path the frontend
uses), with the fake extractor standing in for Groq."""


def _node_count(body):
    return len(body["nodes"])


def _edge_count(body):
    return len(body["edges"])


def test_graph_grows_from_half_info_without_duplicating(api_client):
    # (1) create a company with only dm.name set
    created = api_client.post(
        "/api/companies",
        json={"name": "Acceptance Co", "dm": {"name": "Jane Doe"}},
    ).json()
    company_id = created["id"]

    graph_1 = api_client.get(f"/api/companies/{company_id}/graph").json()
    types_1 = sorted(n["type"] for n in graph_1["nodes"])
    assert types_1 == ["Company", "Person"]  # exactly the Company node + the DM's Person node
    assert _edge_count(graph_1) == 1  # Jane Doe -WORKS_AT-> Acceptance Co

    # (2) add a category + a free-text note in the same save
    api_client.put(
        f"/api/companies/{company_id}",
        json={
            "meta": {"category": "HVAC & IAQ"},
            "checks": {},
            "notes": {"ops": "Jane Doe works closely with John Smith on vendor relationships."},
            "buckets": {},
            "dm": {"name": "Jane Doe"},
        },
    )
    graph_2 = api_client.get(f"/api/companies/{company_id}/graph").json()
    names_2 = {n["name"] for n in graph_2["nodes"]}
    assert "Jane Doe" in names_2  # prior node untouched, still present
    assert "HVAC & IAQ" in names_2  # new: from the mapper
    assert "John Smith" in names_2  # new: from the (fake) text extractor
    jane_nodes = [n for n in graph_2["nodes"] if n["name"] == "Jane Doe"]
    assert len(jane_nodes) == 1  # not duplicated across saves
    node_count_after_growth = _node_count(graph_2)
    edge_count_after_growth = _edge_count(graph_2)
    assert node_count_after_growth > _node_count(graph_1)  # graph actually grew

    # (3) re-save identical content — must be idempotent, not grow further
    api_client.put(
        f"/api/companies/{company_id}",
        json={
            "meta": {"category": "HVAC & IAQ"},
            "checks": {},
            "notes": {"ops": "Jane Doe works closely with John Smith on vendor relationships."},
            "buckets": {},
            "dm": {"name": "Jane Doe"},
        },
    )
    graph_3 = api_client.get(f"/api/companies/{company_id}/graph").json()
    assert _node_count(graph_3) == node_count_after_growth
    assert _edge_count(graph_3) == edge_count_after_growth
