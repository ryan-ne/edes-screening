# Beneficiary Screening

This local web app with a REST API screens program **beneficiaries/participants** against donor-required sanctions and debarment lists. It also produces the screening report you submit to your donor.

- Import an Excel or CSV list of 100+ people. Column names are detected automatically, local-script names are supported, and duplicates are removed.
- Each person is screened via the [OpenSanctions](https://www.opensanctions.org/api/) match API, which offers free API keys for non-profit/non-commercial use. It covers OFAC, the UN, the EU, the UK, World Bank debarment and SAM.gov.
- A review queue lets staff mark each potential match as **cleared** (a false positive) or **escalated**, with a note. Every decision is kept as an audit trail.
- Reports come as a **PDF for the donor** (beneficiary IDs only by default) and **Excel** (the full internal version or IDs only).
- You can re-screen a batch later, and the history of every run is kept.
- An optional Claude API feature writes a plain-language assessment of each potential match.

> Potential matches come from name similarity. A potential match is **not** a determination that a person is listed. Always review matches before reporting them.

## Setup (Windows)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:
- `ORG_NAME`: your organization's name, which is printed on the reports.
- `OPENSANCTIONS_API_KEY`: your API key. **Without a key, the app runs in demo mode against a fictional watchlist.**
- `SCREENING_DATASETS`: set this to match the lists your donor requires.
- `ANTHROPIC_API_KEY` (optional): turns on the AI summaries.

## Run

```bash
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The API docs are at http://127.0.0.1:8000/docs.

## Matching rules

Names are expected to come from ID documents, so exact matches matter most:

| Result | When |
|---|---|
| **Strong** | Exact same name as a list entry or one of its aliases (any word order; case, accents and a leading title like U / Daw / Mr ignored), with the birth year the same or unknown. Also a very close fuzzy match (score ≥ `STRONG_THRESHOLD`) with the same birth year |
| **Possible** | Exact name with a different birth year, or a similar name scoring ≥ `POSSIBLE_THRESHOLD` (default 0.7) |
| hidden | Weaker similarities |

## EU compliance mode

Choose **EU restrictive measures** as the screening standard on upload. This is the default; you can change it with `DEFAULT_PROFILE=eu|multi`. In this mode:
- Only the EU Consolidated Financial Sanctions List is screened.
- **EU compliance report (PDF)** contains the screening details, contract reference, list version, results, method, a declaration with a signature/stamp block, Annex 1 (every participant and their result) and Annex 2 (side-by-side evidence and review decision for each match).
- The report is watermarked DRAFT until every match is reviewed, and DEMO when using the fictional test list.

## Deploy to a server

See [DEPLOY.md](DEPLOY.md). It covers Docker Compose, automatic HTTPS with Caddy, the team password login, and backups.

## Input file

| Column (any of these names) | Required |
|---|---|
| Name / Full Name (or First Name + Last Name) | yes |
| ID / Beneficiary ID | recommended. This ID appears in the donor PDF instead of the name |
| Other names / Local name. Separate several with `;` | no |
| Date of birth / DOB / Year of birth | recommended. It cuts false positives a lot |
| Country / Nationality | no |
| Type (Person / Organization) | no |

See `sample_data/beneficiaries_sample.csv`.

## REST API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/batches` | Upload a file (multipart: `file`, `name`, `donor_name`) and start screening |
| GET | `/api/batches/{id}` | Batch, its runs, and statistics |
| POST | `/api/batches/{id}/rescreen` | New screening run |
| GET | `/api/runs/{id}` | Run progress and statistics |
| GET | `/api/runs/{id}/results?flagged_only=true` | Results |
| POST | `/api/results/{id}/review` | `{"decision":"cleared|escalated","note":"...","reviewer":"..."}` |
| POST | `/api/screen` | Screen a single person (not stored) |
| GET | `/runs/{id}/report.pdf?names=false` | Donor PDF |
| GET | `/runs/{id}/report.xlsx?names=true` | Excel report |

## Privacy

- The app binds to `127.0.0.1`, so only your PC can reach it. Data is stored in `data/screening.db`, which is gitignored.
- Only the name, other names, DOB and country are sent to OpenSanctions.
- When Claude summaries are on, only potential-match evidence is sent: name, birth year and country. IDs are never sent.
- The PDF uses the built-in Helvetica font, so non-Latin names in a "PDF with names" will not render. Use the romanized name column, or the Excel export, for those.

## Tests

```bash
.venv\Scripts\python -m pytest -q
```
