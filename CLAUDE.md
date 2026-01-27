# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kreditkarten-Abgleich App - A web application for automatically reconciling credit card statements with receipts. The app imports credit card statements (CSV/PDF), auto-categorizes transactions using Claude AI, matches receipts, and generates reconciliation reports.

**Language**: German (code, UI, comments)

## Development Environment (DDEV)

This project runs in DDEV with a custom Python/Flask service.

```bash
# Start development environment
ddev start

# Restart after code changes (auto-reload not enabled)
ddev restart

# View logs
ddev logs -s kreditkarten

# Execute commands in kreditkarten container
ddev exec -s kreditkarten python /app/fix_script.py
ddev exec -s kreditkarten "curl -s localhost:5000/health"

# Run tests
ddev exec -s kreditkarten pytest

# Access the app
open http://kreditkarten.ddev.site
```

### Container Structure
- **kreditkarten**: Flask app on port 5000 (internal), served via Traefik
- **health**: Health check aggregator on port 8080
- **web**: DDEV nginx (not used for this app)
- **db**: PostgreSQL 16 (not used - app uses SQLite)

The Flask app code is in `services/kreditkarten/` and mounted at `/app` in the container.

## Tech Stack

- **Backend**: Flask (Python 3.11) with Gunicorn
- **Frontend**: Materialize CSS + Vanilla JS (no build tools)
- **Database**: SQLite at `/app/data/kreditkarten.db`
- **AI**: Claude API (Sonnet) for categorization and receipt extraction
- **Export**: openpyxl (Excel), ReportLab (PDF)

## Key Files

| Path | Purpose |
|------|---------|
| `services/kreditkarten/app.py` | Main Flask application (~2500 lines) |
| `services/kreditkarten/parsers/csv_parser.py` | Bank-specific CSV parsing with date validation |
| `services/kreditkarten/parsers/beleg_parser.py` | Receipt OCR extraction via Claude API |
| `services/kreditkarten/matching.py` | Receipt-to-transaction matching algorithm |
| `services/kreditkarten/templates/index.html` | Single-page UI (Materialize + vanilla JS) |
| `.ddev/docker-compose.kreditkarten.yaml` | DDEV service configuration |

## Environment Variables

Required in `services/kreditkarten/.env`:
- `ANTHROPIC_API_KEY` - Claude API key for AI features
- `ENCRYPTION_KEY` - Fernet key for sensitive data

## Architecture Notes

### Database Schema
Tables: `konten` (accounts), `abrechnungen` (statements), `transaktionen` (transactions), `belege` (receipts), `kategorie_regeln` (categorization rules), `bewirtungsbelege` (entertainment receipts), `personen` (guests). See `services/kreditkarten/BRIEFING.md` for full schema.

### Statement Status Logic
A statement (`abrechnung`) is automatically marked as `abgeschlossen` when all its transactions have status `zugeordnet` or `ignoriert`. Status is calculated dynamically on each API call, not stored.

### CSV Import Validation
The import validates transaction dates against the billing period and auto-corrects systematic year errors (e.g., all dates showing 2026 when period is December 2025).

### Matching Algorithm
Receipt-to-transaction matching uses weighted scoring:
- Exact amount match: +0.5 (within €0.01)
- Date proximity: +0.3 (same day) to +0.1 (within 7 days)
- Merchant name similarity: up to +0.2 (fuzzy matching)
- Auto-match threshold: 0.5 confidence

### Bank CSV Formats
Defined in `parsers/csv_parser.py` BANK_FORMATS dict. Supports: Amex (UTF-8, comma), Visa DKB (ISO-8859-1, semicolon), Mastercard Sparkasse.

### Export Structure
Exports follow `exports/{Year}/{MM_MonthName}/` pattern with German month names (Januar, Februar, etc.)
