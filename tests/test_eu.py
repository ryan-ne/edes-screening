import sqlite3

from app import db


def _upload(client, sample_csv, profile):
    r = client.post("/api/batches", files={"file": ("b.csv", sample_csv, "text/csv")},
                    data={"name": "EU batch", "donor_name": "European Union",
                          "contract_ref": "NDICI-TEST/2026/1", "profile": profile})
    assert r.status_code == 201, r.text
    return r.json()


def test_eu_profile_screens_eu_list_only(client, sample_csv):
    up = _upload(client, sample_csv, "eu")
    run = client.get(f"/api/runs/{up['run_id']}").json()
    assert run["datasets"] == ["eu_fsf"]
    batch = client.get(f"/api/batches/{up['batch_id']}").json()
    assert batch["profile"] == "eu" and batch["contract_ref"] == "NDICI-TEST/2026/1"

    flagged = {r["ref_id"]: r for r in client.get(f"/api/runs/{up['run_id']}/results",
                                                  params={"flagged_only": True}).json()}
    assert flagged["B-001"]["status"] == "strong"      # exact name + DOB
    assert flagged["B-011"]["status"] == "strong"      # "U " title ignored
    assert flagged["B-003"]["status"] == "possible"    # exact name, DOB differs
    assert flagged["B-012"]["status"] == "possible"    # similar spelling
    assert "B-006" not in flagged


def test_eu_report_pdf(client, sample_csv):
    up = _upload(client, sample_csv, "eu")
    r = client.get(f"/runs/{up['run_id']}/eu-report.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert len(r.content) > 3000

    # review everything, report should still build (non-draft path)
    for res in client.get(f"/api/runs/{up['run_id']}/results", params={"flagged_only": True}).json():
        client.post(f"/api/results/{res['id']}/review",
                    json={"decision": "cleared", "note": "Different DOB", "reviewer": "QA"})
    assert client.get(f"/api/runs/{up['run_id']}").json()["stats"]["pending"] == 0
    assert client.get(f"/runs/{up['run_id']}/eu-report.pdf").status_code == 200


def test_run_page_split_and_review_page(client, sample_csv):
    up = _upload(client, sample_csv, "eu")
    page = client.get(f"/runs/{up['run_id']}").text
    assert "Waiting for review" in page and "EU compliance report" in page
    assert "Exact name" in page and "Similar name" in page
    rid = client.get(f"/api/runs/{up['run_id']}/results", params={"flagged_only": True}).json()[0]["id"]
    detail = client.get(f"/results/{rid}").text
    assert "Sanctions list entry" in detail and "Different person" in detail


def test_bad_profile_rejected(client, sample_csv):
    r = client.post("/api/batches", files={"file": ("b.csv", sample_csv, "text/csv")}, data={"profile": "xx"})
    assert r.status_code == 400


def test_migration_adds_columns(tmp_path):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE batches (id INTEGER PRIMARY KEY, name TEXT NOT NULL, donor_name TEXT,"
                 " source_file TEXT, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO batches (name, created_at) VALUES ('old', 'x')")
    conn.commit()
    conn.close()
    db.init_db(old)
    conn = sqlite3.connect(old)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(batches)")}
    assert {"profile", "contract_ref"} <= cols
    assert conn.execute("SELECT profile FROM batches").fetchone()[0] == "multi"
    conn.close()
