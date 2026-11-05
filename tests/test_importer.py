import io

import pytest
from openpyxl import Workbook

from app.importer import build_persons, clean_date, guess_mapping, import_file


def test_guess_mapping_handles_varied_headers():
    m = guess_mapping(["Beneficiary ID", "Full Name", "Local Name", "D.O.B", "Nationality"])
    assert m["ref_id"] == "Beneficiary ID"
    assert m["name"] == "Full Name"
    assert m["alt_names"] == "Local Name"
    assert m["country"] == "Nationality"


def test_sample_csv_import(sample_csv):
    res = import_file("sample.csv", sample_csv)
    assert len(res.persons) == 8           # 10 rows - 1 empty - 1 duplicate
    assert res.duplicates == 1
    first = res.persons[0]
    assert first["ref_id"] == "B-001"
    assert first["alt_names"] == ["အောင်စမ်းသပ်"]   # local script kept
    assert first["birth_date"] == "1978"
    org = next(p for p in res.persons if p["ref_id"] == "B-007")
    assert org["entity_type"] == "Organization"


def test_first_last_name_columns():
    res = build_persons(["First Name", "Surname"], [{"First Name": "Ann", "Surname": "Lee"}])
    assert res.persons[0]["name"] == "Ann Lee"
    assert res.persons[0]["ref_id"] == "ROW-2"


def test_missing_name_column_errors():
    with pytest.raises(ValueError, match="name column"):
        build_persons(["Foo"], [{"Foo": "x"}])


def test_xlsx_import():
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "DOB"])
    ws.append(["Test Person", "1980-02-03"])
    buf = io.BytesIO()
    wb.save(buf)
    res = import_file("x.xlsx", buf.getvalue())
    assert res.persons[0]["birth_date"] == "1980-02-03"


@pytest.mark.parametrize("raw,expected", [
    ("12/03/1992", "1992-03-12"), ("1992-03-12", "1992-03-12"), (1985, "1985"),
    ("1985", "1985"), ("garbage", None), ("", None),
])
def test_clean_date(raw, expected):
    assert clean_date(raw) == expected
