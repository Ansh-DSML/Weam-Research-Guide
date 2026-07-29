import json
from pathlib import Path

LOG_FILE = (Path(__file__).resolve().parents[1] / ".." / "logs" / "app.log").resolve()


def _read_log_lines():
    with open(LOG_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_request_completed_log_has_expected_fields(api_client):
    resp = api_client.get("/api/companies")
    rid = resp.headers["x-request-id"]

    lines = _read_log_lines()
    matching = [
        line for line in lines if line.get("request_id") == rid and line.get("message") == "request_completed"
    ]
    assert matching, "no request_completed log line found for this request"
    line = matching[-1]
    assert line["method"] == "GET"
    assert line["path"] == "/api/companies"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], (int, float))


def test_sensitive_note_content_never_logged(api_client):
    unique_marker = "SENTINEL-DO-NOT-LOG-8f3c9a1d"
    created = api_client.post("/api/companies", json={"name": "Log Redaction Test Co"}).json()
    api_client.put(
        f"/api/companies/{created['id']}",
        json={"meta": {}, "checks": {}, "notes": {"ops": unique_marker}, "buckets": {}, "dm": {}},
    )

    raw_text = LOG_FILE.read_text(encoding="utf-8")
    assert unique_marker not in raw_text, "a research-note value leaked into the log file!"


def test_404_logged_with_correct_status_not_masked_as_success(api_client):
    resp = api_client.put(
        "/api/companies/999999",
        json={"meta": {}, "checks": {}, "notes": {}, "buckets": {}, "dm": {}},
    )
    assert resp.status_code == 404
    rid = resp.headers["x-request-id"]

    lines = _read_log_lines()
    matching = [line for line in lines if line.get("request_id") == rid]
    assert any(line["message"] == "request_completed" and line["status"] == 404 for line in matching)
