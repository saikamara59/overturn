import io

from server.models import Claim, Run
from tests.conftest import SAMPLE_CSV  # 3 claims: CLM-001/002/003
from tests.server.conftest import login


def upload(client, *, content=SAMPLE_CSV, name="denials.csv", dry_run=True):
    return client.post(
        "/api/v1/runs",
        files={"file": (name, io.BytesIO(content.encode()), "text/csv")},
        data={"dry_run": "true" if dry_run else "false"},
    )


def test_upload_requires_auth(client):
    assert upload(client).status_code == 401


def test_upload_creates_run_and_claims(client, session_factory):
    login(client)
    r = upload(client)
    assert r.status_code == 202, r.text
    run_id = r.json()["runId"]
    with session_factory() as s:
        run = s.query(Run).one()
        assert str(run.id) == run_id
        assert run.status == "queued" and run.dry_run is True
        assert run.total_records == 3
        assert float(run.total_billed) == 21230.25
        claims = s.query(Claim).order_by(Claim.claim_id).all()
        assert [c.claim_id for c in claims] == ["CLM-001", "CLM-002", "CLM-003"]
        assert all(c.status == "queued" for c in claims)


def test_upload_rejects_bad_rows_with_422(client):
    login(client)
    bad = SAMPLE_CSV.replace("12500.00", "not-a-number")
    r = upload(client, content=bad)
    assert r.status_code == 422
    assert "row 0" in r.json()["detail"]


def test_upload_rejects_wrong_extension_415(client):
    login(client)
    assert upload(client, name="denials.txt").status_code == 415


def test_upload_record_cap_413(client, settings):
    login(client)
    header, row = SAMPLE_CSV.split("\n", 1)[0], SAMPLE_CSV.splitlines()[1]
    big = header + "\n" + "\n".join(
        row.replace("CLM-001", f"CLM-{i:04d}") for i in range(settings.max_upload_records + 1)
    )
    assert upload(client, content=big).status_code == 413


def test_live_upload_without_api_key_422(client):
    login(client)
    r = upload(client, dry_run=False)
    assert r.status_code == 422
    assert "API key" in r.json()["detail"]


def test_list_and_get_runs(client):
    login(client)
    run_id = upload(client).json()["runId"]
    listed = client.get("/api/v1/runs").json()
    assert len(listed) == 1 and listed[0]["id"] == run_id
    got = client.get(f"/api/v1/runs/{run_id}").json()
    assert got["status"] == "queued"
    assert got["totalRecords"] == 3 and got["drafted"] == 0
    assert client.get("/api/v1/runs/00000000-0000-0000-0000-000000000000").status_code == 404


def test_retry_requeues_unfinished_claims(client, session_factory):
    login(client)
    run_id = upload(client).json()["runId"]
    with session_factory() as s:
        claims = s.query(Claim).order_by(Claim.claim_id).all()
        claims[0].status = "draft_ready"
        claims[1].status = "failed"
        claims[2].status = "drafting"
        run = s.query(Run).one()
        run.status = "failed"
        run.drafted = 1
        run.failed_records = 1
        s.commit()
    r = client.post(f"/api/v1/runs/{run_id}/retry")
    assert r.status_code == 200 and r.json() == {"requeued": 2}
    with session_factory() as s:
        statuses = {c.claim_id: c.status for c in s.query(Claim).all()}
        assert statuses["CLM-001"] == "draft_ready"
        assert statuses["CLM-002"] == "queued" and statuses["CLM-003"] == "queued"
        run = s.query(Run).one()
        assert run.status == "queued"
        assert run.drafted == 1
        assert run.failed_records == 0
