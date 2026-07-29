"""The literal regression test for the reported bug: 'state gets flushed if the
laptop is shut down for a while.' This runs a real uvicorn process against the
real Postgres container (whichever it's named — discovered by port, see below) — not the
disposable per-test schema
used by the rest of the suite — and proves data survives both a DB container
restart and a backend process restart.

This test is slower and touches real Docker infrastructure on purpose: it is the
acceptance gate for Phase 0, not a unit test, and should be run less frequently
than the fast suite (e.g. before considering Phase 0 "done").
"""

import socket
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PYTHON_EXE = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
PORT = 8010
BASE_URL = f"http://127.0.0.1:{PORT}"
DB_HOST_PORT = 5433
ADMIN_URL = "postgresql://weam:weam_dev_local_only@localhost:5433/weam_research"
SERVER_LOG = BACKEND_DIR.parent / "logs" / "durability_test_server.log"


def _find_db_container_name() -> str:
    """The Postgres container's name depends on how it was started — a plain `docker run
    --name weam-research-db ...` (the README's fallback) names it exactly that, but
    `docker compose up` names it after the compose project (e.g. `backend-db-1`). Hardcoding
    either name makes this test fail on the other setup path for a reason that has nothing to
    do with a real regression, so discover it by the port it actually publishes instead."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"publish={DB_HOST_PORT}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    if not names:
        raise RuntimeError(
            f"No running container found publishing port {DB_HOST_PORT} — start Postgres first "
            f"(`docker compose up -d` or the docker run fallback in the README)."
        )
    return names[0]


def _wait_for(predicate, timeout_s=30, interval_s=0.5) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_port_from_leftover_process(port: int):
    """A previous crashed/interrupted test run can leak an orphaned server process on this
    port. We deliberately do NOT auto-remediate by spawning a powershell/WMI process to find
    and kill the owner: measured in this environment, spawning that one extra process added
    several minutes of latency (almost certainly endpoint security software intercepting new
    process creation) — far more expensive than the problem it would solve. Failing fast with
    a clear, actionable message is safer and faster than silent auto-remediation here."""
    if _port_is_open(port):
        raise RuntimeError(
            f"port {port} is already in use — a previous test run likely left a server "
            f"process running. Free it manually (e.g. find the PID with "
            f"`netstat -ano | findstr :{port}` and `taskkill /F /PID <pid>`) and re-run."
        )


def _start_server():
    _free_port_from_leftover_process(PORT)
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(SERVER_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [str(PYTHON_EXE), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(BACKEND_DIR),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )

    def is_up():
        try:
            return httpx.get(f"{BASE_URL}/api/health", timeout=1).status_code in (200, 503)
        except Exception:
            return False

    try:
        assert _wait_for(is_up, timeout_s=20), "server never came up"
    except AssertionError:
        proc.kill()
        raise
    return proc


def _stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    # the process exiting doesn't guarantee Windows has released the socket yet —
    # wait for it explicitly so the next _start_server() doesn't race an in-progress teardown.
    _wait_for(lambda: not _port_is_open(PORT), timeout_s=10, interval_s=0.25)


def _cleanup_row(name: str):
    conn = psycopg.connect(ADMIN_URL, autocommit=True)
    conn.execute("DELETE FROM companies WHERE name = %s", (name,))
    conn.close()


@pytest.fixture()
def live_server():
    proc = _start_server()
    yield
    _stop_server(proc)


def test_data_survives_db_container_stop_start(live_server):
    """The exact repro: create data, take the DB down (simulating shutdown), bring it
    back, confirm the data is still there byte-for-byte."""
    unique_name = "Durability-Gate-DB-Restart-Co"
    _cleanup_row(unique_name)  # self-heal against a leftover row from an interrupted prior run
    try:
        created = httpx.post(
            f"{BASE_URL}/api/companies",
            json={"name": unique_name},
            timeout=5,
        ).json()
        company_id = created["id"]
        httpx.put(
            f"{BASE_URL}/api/companies/{company_id}",
            json={"meta": {}, "checks": {}, "notes": {"ops": "critical finding — must survive restart"}, "buckets": {}, "dm": {}},
            timeout=5,
        )

        container_name = _find_db_container_name()
        stop_result = _docker("stop", container_name)
        assert stop_result.returncode == 0, stop_result.stderr

        # NOTE: a health check hitting a just-stopped DB takes ~2-4s to fail (bounded by the
        # engine's connect_timeout=2 in app/db.py, sometimes doubled by an internal retry) —
        # the client-side timeout here must comfortably exceed that or health_degraded() can
        # never observe a True in time and this assertion fails even though the app is correct.
        def health_degraded():
            try:
                return httpx.get(f"{BASE_URL}/api/health", timeout=6).status_code == 503
            except Exception:
                return False

        assert _wait_for(health_degraded, timeout_s=25, interval_s=1), "health check never reported the DB as down"

        start_result = _docker("start", container_name)
        assert start_result.returncode == 0, start_result.stderr

        def health_ok():
            try:
                return httpx.get(f"{BASE_URL}/api/health", timeout=6).status_code == 200
            except Exception:
                return False

        assert _wait_for(health_ok, timeout_s=30, interval_s=1), "DB never came back healthy after restart"

        docs = httpx.get(f"{BASE_URL}/api/companies", timeout=5).json()
        match = [d for d in docs if d["id"] == company_id]
        assert match, "DATA LOST after DB container restart — this is the exact bug this project exists to fix"
        assert match[0]["notes"] == {"ops": "critical finding — must survive restart"}
    finally:
        _cleanup_row(unique_name)


def test_data_survives_backend_process_restart():
    """Second variant: kill and restart the backend process itself (crash/redeploy),
    DB left running throughout. Proves there's no load-bearing in-memory state."""
    unique_name = "Durability-Gate-Backend-Restart-Co"
    _cleanup_row(unique_name)  # self-heal against a leftover row from an interrupted prior run
    proc = _start_server()
    try:
        created = httpx.post(f"{BASE_URL}/api/companies", json={"name": unique_name}, timeout=5).json()
        company_id = created["id"]

        _stop_server(proc)

        proc = _start_server()

        docs = httpx.get(f"{BASE_URL}/api/companies", timeout=5).json()
        match = [d for d in docs if d["id"] == company_id]
        assert match, "DATA LOST after backend process restart"
    finally:
        _stop_server(proc)
        _cleanup_row(unique_name)
