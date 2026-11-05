from app.config import settings


def _upload(client, sample_csv, **data):
    r = client.post("/api/batches", files={"file": ("b.csv", sample_csv, "text/csv")},
                    data={"name": "EDES batch", "donor_name": "European Union", **data})
    assert r.status_code == 201, r.text
    return r.json()


def test_default_profile_is_edes(client, sample_csv):
    assert settings.default_profile == "edes"
    up = _upload(client, sample_csv)  # no profile given
    assert client.get(f"/api/batches/{up['batch_id']}").json()["profile"] == "edes"
    assert client.get(f"/api/runs/{up['run_id']}").json()["datasets"] == ["eu_edes"]


def test_edes_report_wording(client, sample_csv):
    up = _upload(client, sample_csv, profile="edes", contract_ref="TEST/1")
    page = client.get(f"/runs/{up['run_id']}").text
    assert "EDES compliance report" in page
    pdf = client.get(f"/runs/{up['run_id']}/eu-report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_edes_texts_differ_from_sanctions():
    from app.reports.eu_pdf import TEXTS
    assert "EDES" in TEXTS["edes"]["subtitle"] and "restrictive" not in TEXTS["edes"]["declaration"]
    assert "EDES-DB" in TEXTS["edes"]["note"]
