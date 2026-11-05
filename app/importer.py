"""Read beneficiary lists from CSV / Excel, auto-map columns, clean and dedupe."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook

# Header synonyms (lower-cased, punctuation stripped) -> canonical field
COLUMN_ALIASES: dict[str, list[str]] = {
    "ref_id": ["id", "ref", "ref id", "beneficiary id", "participant id", "code", "no", "number", "case id"],
    "name": ["name", "full name", "fullname", "beneficiary name", "participant name",
             "english name", "name english", "name en", "romanized name", "organization name"],
    "first_name": ["first name", "firstname", "given name"],
    "last_name": ["last name", "lastname", "surname", "family name"],
    "alt_names": ["alt name", "alt names", "other names", "alias", "aliases", "local name",
                  "name local", "native name", "other spelling", "other spellings", "local script name"],
    "birth_date": ["dob", "date of birth", "birth date", "birthdate", "birthday", "year of birth", "birth year"],
    "country": ["country", "nationality", "citizenship", "country of residence"],
    "entity_type": ["type", "entity type", "person or organization", "kind"],
}


def _norm_header(h: Any) -> str:
    s = str(h or "").strip().lower()
    s = re.sub(r"[_\-./()]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def guess_mapping(headers: list[str]) -> dict[str, str]:
    """Return {canonical_field: original_header} for headers we recognise."""
    mapping: dict[str, str] = {}
    normed = {_norm_header(h): h for h in headers}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normed and field_name not in mapping:
                mapping[field_name] = normed[alias]
                break
    return mapping


def read_table(filename: str, content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Read first sheet / CSV into (headers, rows)."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        headers: list[str] = []
        for first in it:  # skip leading empty rows
            if any(c not in (None, "") for c in first):
                headers = [str(c).strip() if c is not None else f"col{i+1}" for i, c in enumerate(first)]
                break
        data = [dict(zip(headers, r)) for r in it if any(c not in (None, "") for c in r)]
        return headers, data
    if lower.endswith((".csv", ".txt")):
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("Could not decode CSV file — please save it as UTF-8.")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        data = [{(k or "").strip(): v for k, v in r.items()}
                for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
        return headers, data
    raise ValueError("Unsupported file type. Upload .xlsx or .csv")


def clean_name(s: Any) -> str:
    s = unicodedata.normalize("NFC", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def match_key(s: str) -> str:
    """Accent/case-insensitive key for dedupe."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", "", s)


def clean_date(v: Any) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and 1900 <= int(v) <= 2100:
        return str(int(v))  # year only
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.fullmatch(r"(19|20)\d{2}", s)
    return s if m else None


def clean_type(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s.startswith(("org", "company", "entity", "business", "ngo", "cso")):
        return "Organization"
    return "Person"


@dataclass
class ImportResult:
    persons: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)
    duplicates: int = 0


def build_persons(headers: list[str], data: list[dict[str, Any]],
                  mapping: dict[str, str] | None = None) -> ImportResult:
    res = ImportResult(mapping=mapping or guess_mapping(headers))
    m = res.mapping
    if "name" not in m and not ("first_name" in m or "last_name" in m):
        raise ValueError(
            "Could not find a name column. Expected a header like 'Name' or 'Full Name' "
            f"(found: {', '.join(headers)})."
        )
    seen: dict[str, int] = {}
    for i, r in enumerate(data, start=2):  # row 1 = header
        if "name" in m:
            name = clean_name(r.get(m["name"]))
        else:
            name = clean_name(f"{r.get(m.get('first_name', ''), '') or ''} {r.get(m.get('last_name', ''), '') or ''}")
        if not name:
            res.warnings.append(f"Row {i}: empty name — skipped.")
            continue
        alt_raw = r.get(m["alt_names"]) if "alt_names" in m else None
        alt_names = [clean_name(a) for a in re.split(r"[;|\n]", str(alt_raw or "")) if clean_name(a)]
        alt_names = [a for a in alt_names if match_key(a) != match_key(name)]
        dob_raw = r.get(m["birth_date"]) if "birth_date" in m else None
        dob = clean_date(dob_raw)
        if dob_raw not in (None, "") and dob is None:
            res.warnings.append(f"Row {i}: could not read date of birth '{dob_raw}' — ignored.")
        ref_id = clean_name(r.get(m["ref_id"])) if "ref_id" in m else ""
        person = {
            "ref_id": ref_id or f"ROW-{i}",
            "name": name,
            "alt_names": alt_names,
            "birth_date": dob,
            "country": clean_name(r.get(m["country"])) if "country" in m else None,
            "entity_type": clean_type(r.get(m["entity_type"])) if "entity_type" in m else "Person",
        }
        key = f"{match_key(name)}|{dob or ''}"
        if key in seen:
            res.duplicates += 1
            res.warnings.append(f"Row {i}: duplicate of {res.persons[seen[key]]['ref_id']} ({name}) — skipped.")
            continue
        seen[key] = len(res.persons)
        res.persons.append(person)
    return res


def import_file(filename: str, content: bytes) -> ImportResult:
    headers, data = read_table(filename, content)
    if not data:
        raise ValueError("File has no data rows.")
    return build_persons(headers, data)
