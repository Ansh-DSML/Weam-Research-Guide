def test_create_returns_201_and_id(api_client):
    resp = api_client.post("/api/companies", json={"name": "Acme"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme"
    assert isinstance(body["id"], int)


def test_list_includes_created_company(api_client):
    api_client.post("/api/companies", json={"name": "Acme"})
    resp = api_client.get("/api/companies")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Acme" in names


def test_update_existing_reflects_change(api_client):
    created = api_client.post("/api/companies", json={"name": "Acme"}).json()
    resp = api_client.put(
        f"/api/companies/{created['id']}",
        json={"meta": {"category": "Plumbing"}, "checks": {}, "notes": {}, "buckets": {}, "dm": {}},
    )
    assert resp.status_code == 200
    assert resp.json()["meta"] == {"category": "Plumbing"}


def test_update_unknown_id_returns_404(api_client):
    resp = api_client.put(
        "/api/companies/999999",
        json={"meta": {}, "checks": {}, "notes": {}, "buckets": {}, "dm": {}},
    )
    assert resp.status_code == 404


def test_rename_to_free_name_returns_200(api_client):
    created = api_client.post("/api/companies", json={"name": "Old"}).json()
    resp = api_client.post(f"/api/companies/{created['id']}/rename", json={"new_name": "New"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_rename_to_taken_name_returns_409(api_client):
    api_client.post("/api/companies", json={"name": "Taken"})
    other = api_client.post("/api/companies", json={"name": "Free"}).json()
    resp = api_client.post(f"/api/companies/{other['id']}/rename", json={"new_name": "Taken"})
    assert resp.status_code == 409


def test_create_duplicate_name_returns_409(api_client):
    api_client.post("/api/companies", json={"name": "Acme"})
    resp = api_client.post("/api/companies", json={"name": "Acme"})
    assert resp.status_code == 409


def test_malformed_body_returns_422(api_client):
    resp = api_client.post("/api/companies", json={"name": ""})
    assert resp.status_code == 422

    resp2 = api_client.post("/api/companies", json={"checks": "not-a-dict-should-be-object"})
    assert resp2.status_code == 422


def test_oversized_body_returns_413(api_client):
    huge_notes = {"section1": "x" * 3_000_000}  # exceeds max_request_body_bytes (2MB)
    resp = api_client.post("/api/companies", json={"name": "Huge", "notes": huge_notes})
    assert resp.status_code == 413


def test_unicode_and_special_char_name_roundtrips_over_http(api_client):
    name = "Acme & Co / Tëst Ünïcödé 株式会社"
    created = api_client.post("/api/companies", json={"name": name}).json()
    assert created["name"] == name
    fetched = api_client.get("/api/companies").json()
    assert any(c["name"] == name for c in fetched)


def test_health_endpoint_reports_db_ok(api_client):
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["db"] is True


def test_request_id_header_present_on_every_response(api_client):
    resp = api_client.get("/api/companies")
    assert "x-request-id" in resp.headers
