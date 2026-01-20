# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kreditkarten-Abgleich App - A web application for automatically reconciling credit card statements with receipts. The app imports credit card statements (CSV/PDF), auto-categorizes transactions using Claude AI, matches receipts, and generates reconciliation reports.

**Language**: German (code, UI, comments)

## Tech Stack

- **Backend**: Flask (Python 3.11) with Gunicorn
- **Frontend**: Materialize CSS + Vanilla JS (no build tools)
- **Database**: SQLite
- **AI**: Claude API (Sonnet) for categorization and receipt extraction
- **Export**: openpyxl (Excel), ReportLab (PDF)
- **Container**: Docker with Traefik reverse proxy

## Project Structure

```
kreditkarten-app/
├── app.py                 # Main Flask application
├── cli.py                 # CLI for batch processing
├── matching.py            # Receipt-transaction matching algorithms
├── parsers/
│   ├── csv_parser.py      # Bank-specific CSV parsers
│   ├── pdf_parser.py      # PDF statement parser
│   └── beleg_parser.py    # Receipt extraction
├── templates/
│   └── index.html         # Single-page web UI
├── data/
│   ├── kreditkarten.db    # SQLite database
│   └── .cache.json        # Processing cache
├── imports/inbox/         # New statements to process
├── belege/inbox/          # New receipts to match
├── exports/               # Generated reports (Year/Month structure)
├── referenz-code/         # Reference implementation from Spesen-App
└── docker-compose.yml     # Container orchestration with Traefik
```

## Development Commands

```bash
# Setup with uv
uv sync

# Run Flask development server
uv run python app.py

# Run with Docker
docker compose up --build
```

## Environment Variables

Required in `.env`:
- `ANTHROPIC_API_KEY` - Claude API key for AI features
- `ENCRYPTION_KEY` - Fernet key for sensitive data (generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)

Optional:
- `DATA_DIR` - Database and cache location (default: `./data`)
- `EXPORTS_DIR` - Export output location (default: `./exports`)
- `GUNICORN_WORKERS` - Number of Gunicorn workers

## Architecture Notes

### Database Schema
Five main tables: `konten` (accounts), `abrechnungen` (statements), `transaktionen` (transactions), `belege` (receipts), `kategorie_regeln` (categorization rules). See BRIEFING.md for full schema.

### Matching Algorithm
Receipt-to-transaction matching uses weighted scoring:
- Exact amount match: +0.5 (within €0.01)
- Date proximity: +0.3 (same day) to +0.1 (within 7 days)
- Merchant name similarity: up to +0.2 (fuzzy matching)

Threshold for auto-match: 0.5 confidence

### Bank CSV Formats
Parsers support multiple bank formats with different encodings, delimiters, and column mappings. Currently defined: Amex (UTF-8, comma) and Visa DKB (ISO-8859-1, semicolon).

### AI Integration
Claude API is used for:
1. Transaction categorization (merchant normalization, category suggestion with confidence score)
2. Receipt data extraction (amount, date, merchant from OCR text)

Both return structured JSON responses.

### Export Structure
Exports follow `exports/{Year}/{MM_MonthName}/` pattern with German month names.

## Key Patterns from Reference Code

The `referenz-code/` directory contains the complete Spesen-App implementation. Reusable patterns:
- Flask app structure with health check endpoint
- Fernet encryption for sensitive data (IBAN, card numbers)
- Cache management with file hashes
- Excel/PDF generation with consistent styling
- File upload handling with type validation
- EZB currency exchange rate fetching
