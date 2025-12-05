# Kreditkarten-Abgleich

A Flask-based credit card statement reconciliation application for matching receipts (Belege) to transactions.

## Features

- **PDF Statement Parsing**: Automatic extraction of transactions from American Express PDF statements
- **Receipt Management**: Upload and OCR-based extraction of receipt data (amount, date, vendor)
- **Automatic Matching**: Intelligent matching of receipts to transactions based on amount, date, and vendor name
- **Currency Support**: Handles foreign currency transactions (USD, etc.) with adjusted matching weights
- **AI Categorization**: Batch categorization of transactions using Claude API
- **PDF Export**: Generate transaction reports in landscape PDF format with Unicode support
- **ZIP Export**: Download complete package with original statement, all receipts, and PDF report

## Tech Stack

- **Backend**: Python 3.11, Flask, Gunicorn
- **Database**: SQLite
- **PDF Processing**: PyMuPDF (fitz), ReportLab, pdfplumber
- **OCR**: Tesseract (German & English)
- **AI**: Anthropic Claude API
- **Frontend**: Materialize CSS
- **Deployment**: Docker

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Anthropic API Key (for categorization feature)

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/dkd-dobberkau/kreditkarten-app.git
   cd kreditkarten-app
   ```

2. Create environment file:
   ```bash
   cp .env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

3. Start the application:
   ```bash
   docker compose up -d
   ```

4. Open http://localhost:5002 in your browser

## Usage

1. **Upload Statement**: Import your credit card PDF statement via the upload button
2. **Upload Receipts**: Add receipt PDFs to the `belege/inbox` folder or upload via UI
3. **Auto-Match**: Click "Auto-Zuordnung" to automatically match receipts to transactions
4. **Review & Categorize**: Review matches and run AI categorization
5. **Export**: Download PDF report or complete ZIP archive

## Directory Structure

```
kreditkarten-app/
├── app.py              # Main Flask application
├── matching.py         # Matching algorithm
├── parsers/            # PDF and CSV parsers
│   ├── pdf_parser.py   # Amex statement parser
│   ├── beleg_parser.py # Receipt OCR parser
│   └── csv_parser.py   # CSV import support
├── templates/          # HTML templates
├── belege/
│   ├── inbox/          # Upload receipts here
│   └── archiv/         # Processed receipts
├── imports/
│   ├── inbox/          # Upload statements here
│   └── archiv/         # Processed statements
├── data/               # SQLite database
├── exports/            # Generated exports
└── logs/               # Application logs
```

## Configuration

Environment variables (`.env`):

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | API key for Claude AI categorization | Yes |
| `FLASK_DEBUG` | Enable debug mode (0/1) | No |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/abrechnungen` | GET | List all statements |
| `/api/abrechnungen/<id>/transaktionen` | GET | Get transactions for statement |
| `/api/belege` | GET | List all receipts |
| `/api/belege/auto-match` | POST | Run automatic matching |
| `/api/transaktionen/<id>/kategorisiere` | POST | Categorize single transaction |
| `/api/abrechnungen/<id>/kategorisiere-alle` | POST | Batch categorize all transactions |
| `/api/abrechnungen/<id>/export` | GET | Download PDF report |
| `/api/abrechnungen/<id>/export-zip` | GET | Download complete ZIP archive |

## License

MIT License - see [LICENSE](LICENSE) for details.
