import httpx

from app.scoring import classify, evaluate
from app.screening.mock import MockScreener
from app.screening.opensanctions import OpenSanctionsScreener


def test_classify_thresholds():
    assert classify(0.3) == "clear"
    assert classify(0.6) == "possible"
    assert classify(0.9) == "strong"


def test_dob_mismatch_lowers_score():
    person = {"name": "X", "birth_date": "1990-01-01"}
    cand = {"score": 0.95, "birth_dates": ["1965-04-12"], "countries": []}
    status, top, _ = evaluate(person, [cand])
    assert top < 0.8 and status != "strong"


def test_dob_match_keeps_strong():
    person = {"name": "X", "birth_date": "1978"}
    status, top, _ = evaluate(person, [{"score": 0.9, "birth_dates": ["1978-01-01"]}])
    assert status == "strong" and top >= 0.9


def test_country_names_not_penalised():
    # "Myanmar" vs ISO "mm" must not count as a mismatch
    _, top, _ = evaluate({"name": "X", "country": "Myanmar"}, [{"score": 0.85, "countries": ["mm"]}])
    assert top == 0.85


def test_mock_screener_finds_fictional_entry():
    out = MockScreener().screen([{"id": 1, "name": "Aung Test Example", "alt_names": []}], [])
    assert out[1] and out[1][0]["score"] > 0.9


def test_opensanctions_request_and_parse():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"responses": {"7": {"results": [{
            "id": "NK-abc", "caption": "Some Body", "schema": "Person", "score": 0.91,
            "datasets": ["us_ofac_sdn"],
            "properties": {"birthDate": ["1970"], "nationality": ["mm"], "topics": ["sanction"]},
        }]}}})

    client = httpx.Client(transport=httpx.MockTransport(handler),
                          headers={"Authorization": "ApiKey k"})
    s = OpenSanctionsScreener(api_key="k", base_url="https://api.test", client=client)
    out = s.screen([{"id": 7, "name": "Some Body", "alt_names": ["Local"], "birth_date": "1970",
                     "country": "Myanmar", "entity_type": "Person"}], ["us_ofac_sdn"])
    assert "/match/default" in seen["url"] and "include_dataset=us_ofac_sdn" in seen["url"]
    assert seen["auth"] == "ApiKey k"
    assert b'"Local"' in seen["body"] and b"birthDate" in seen["body"]
    c = out[7][0]
    assert c["caption"] == "Some Body" and c["countries"] == ["mm"]
    assert c["url"].endswith("/entities/NK-abc/")
