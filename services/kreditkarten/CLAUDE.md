# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kreditkarten-Abgleich App - Flask backend for reconciling credit card statements with receipts.

**Language**: German (code, UI, comments)

## Development Commands

```bash
# From repo root - restart after code changes
ddev restart

# Run in container
ddev exec -s kreditkarten pytest
ddev exec -s kreditkarten python -c "from parsers import parse_csv; print('OK')"

# Check syntax before restart
python3 -m py_compile app.py parsers/csv_parser.py

# View container logs
ddev logs -s kreditkarten -f
```

## Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | Flask routes, database schema, API endpoints |
| `matching.py` | Weighted scoring algorithm for receipt-transaction matching |
| `parsers/csv_parser.py` | Bank-specific CSV parsing, date validation, auto-correction |
| `parsers/pdf_parser.py` | Amex PDF statement extraction |
| `parsers/beleg_parser.py` | Receipt OCR via Claude API |

## Database

SQLite at `/app/data/kreditkarten.db`. Schema defined in `app.py` `init_db()` function.

Main tables:
- `konten` - Credit card accounts
- `abrechnungen` - Monthly statements (status calculated dynamically)
- `transaktionen` - Individual transactions with category/status
- `belege` - Receipts with extracted data in `extrahierte_daten` JSON
- `bewirtungsbelege` - Entertainment expense receipts with guest list

## API Patterns

- All endpoints under `/api/`
- JSON responses with `success` or `error` field
- Database connections via `get_db()` with `sqlite3.Row` factory
- Retry logic for concurrent writes: `db_execute_with_retry()`

## Import Flow

1. Upload CSV/PDF via `/api/abrechnungen/import`
2. Parser extracts transactions (with date validation)
3. Auto-correction applied if systematic year errors detected
4. Transactions inserted with status `offen`
5. Optional: Auto-match receipts, AI categorization

## Frontend

Single-page app in `templates/index.html`:
- Materialize CSS framework
- Vanilla JavaScript (no build tools)
- API calls via `api()` helper function
- Modals for transaction details, receipt editing
