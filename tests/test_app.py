def _upload(client, sample_csv):
    r = client.post("/api/batches", files={"file": ("benef.csv", sample_csv, "text/csv")},
                    data={"name": "Cohort test", "donor_name": "Test Donor"})
    assert r.status_code == 201, r.text
    return r.json()


def test_end_to_end_api(client, sample_csv):
    up = _upload(client, sample_csv)
    assert up["imported"] == 8 and up["duplicates"] == 1

    # TestClient runs background tasks before returning, so run is done
    run = client.get(f"/api/runs/{up['run_id']}").json()
    assert run["status"] == "done", run
    assert run["stats"]["screened"] == 8
    assert run["stats"]["possible"] + run["stats"]["strong"] >= 2

    flagged = client.get(f"/api/runs/{up['run_id']}/results", params={"flagged_only": True}).json()
    ids = {r["ref_id"] for r in flagged}
    assert "B-001" in ids            # matches fictional "Aung Test Example"
    assert "B-006" not in ids        # ordinary name stays clear

    rid = flagged[0]["id"]
    rv = client.post(f"/api/results/{rid}/review",
                     json={"decision": "cleared", "note": "DOB differs", "reviewer": "QA"})
    assert rv.status_code == 200 and rv.json()["review_decision"] == "cleared"
    bad = client.post(f"/api/results/{rid}/review", json={"decision": "maybe", "reviewer": "QA"})
    assert bad.status_code == 422

    x = client.get(f"/runs/{up['run_id']}/report.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = client.get(f"/runs/{up['run_id']}/report.pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    assert b"Aung" not in p.content  # IDs-only PDF by default

    rs = client.post(f"/api/batches/{up['batch_id']}/rescreen")
    assert rs.status_code == 201
    assert len(client.get(f"/api/batches/{up['batch_id']}").json()["runs"]) == 2


def test_ui_pages_render(client, sample_csv):
    up = _upload(client, sample_csv)
    assert client.get("/").status_code == 200
    page = client.get(f"/runs/{up['run_id']}")
    assert page.status_code == 200 and "Potential matches" in page.text
    assert "built-in method" not in page.text
    flagged = client.get(f"/api/runs/{up['run_id']}/results", params={"flagged_only": True}).json()
    detail = client.get(f"/results/{flagged[0]['id']}")
    assert detail.status_code == 200 and "Decision" in detail.text


def test_single_screen_and_bad_upload(client):
    r = client.post("/api/screen", json={"name": "Viktor Demo Sanctionov", "birth_date": "1965"})
    assert r.status_code == 200 and r.json()["status"] == "strong"
    bad = client.post("/api/batches", files={"file": ("x.pdf", b"nope", "application/pdf")})
    assert bad.status_code == 400
