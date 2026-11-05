"""Exact-name-first matching rules (names come from ID documents)."""
from app.scoring import evaluate, name_tokens


def cand(caption, score=0.6, dobs=(), aliases=()):
    return {"caption": caption, "score": score, "birth_dates": list(dobs), "aliases": list(aliases),
            "datasets": ["eu_fsf"], "countries": []}


def test_exact_name_is_strong_even_with_low_provider_score():
    status, _, kept = evaluate({"name": "Aung Test Example"}, [cand("Aung Test Example", score=0.55)])
    assert status == "strong" and kept[0]["match_type"] == "exact"


def test_exact_name_word_order_case_accents_ignored():
    status, _, _ = evaluate({"name": "EXAMPLE aung test"}, [cand("Aung Tést Example")])
    assert status == "strong"


def test_exact_name_with_title_prefix():
    assert name_tokens("U Aung Test Example") == name_tokens("Aung Test Example")
    assert name_tokens("Daw Khin Win") == name_tokens("Khin Win")
    # two-word names keep the first word (could be a real name, e.g. "Ma Ma")
    assert name_tokens("Ma Thida") != name_tokens("Thida")


def test_exact_alias_match_is_strong():
    status, _, kept = evaluate({"name": "Ko Aung Example"},
                               [cand("Aung Test Example", aliases=["Ko Aung Example"])])
    assert status == "strong" and "Ko Aung Example" in kept[0]["notes"][0]


def test_local_name_column_used_for_exact_match():
    p = {"name": "Something Else", "alt_names": ["Aung Test Example"]}
    assert evaluate(p, [cand("Aung Test Example")])[0] == "strong"


def test_exact_name_but_different_dob_is_possible():
    status, _, kept = evaluate({"name": "Viktor Demo", "birth_date": "1990-01-01"},
                               [cand("Viktor Demo", dobs=["1965"])])
    assert status == "possible" and kept[0]["dob_check"] == "differs"


def test_fuzzy_never_strong_without_dob_match():
    status, _, _ = evaluate({"name": "Aung Test Exampel"}, [cand("Aung Test Example", score=0.97)])
    assert status == "possible"


def test_weak_fuzzy_hidden():
    status, _, kept = evaluate({"name": "Aung Min"}, [cand("Aung Test Example", score=0.6)])
    assert status == "clear" and kept == []


def test_partial_name_not_exact():
    # sharing some words is not an exact match
    status, _, kept = evaluate({"name": "Aung Test"}, [cand("Aung Test Example", score=0.65)])
    assert status == "clear"
