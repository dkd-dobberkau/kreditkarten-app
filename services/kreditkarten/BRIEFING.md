# Kreditkarten-Abgleich App - Briefing

## Projektziel

Eine Web-Applikation zum automatischen Abgleich von Kreditkartenabrechnungen mit Belegen. Die App soll:

1. **Kreditkartenabrechnung importieren** (CSV, PDF)
2. **Transaktionen automatisch kategorisieren** (mit Claude AI)
3. **Belege/Rechnungen zuordnen** (Matching)
4. **Abgleich-Report erstellen** (Excel, PDF)
5. **Offene Posten identifizieren**

---

## Architektur (basierend auf Spesen-App)

### Tech-Stack

| Komponente | Technologie | Begründung |
|------------|-------------|------------|
| Backend | Flask (Python 3.11) | Bewährt, einfach, schnell |
| Frontend | Materialize CSS + Vanilla JS | Responsive, keine Build-Tools |
| Datenbank | SQLite | Lokal, keine Konfiguration |
| AI | Claude API (Sonnet) | Kategorisierung, Extraktion |
| Export | openpyxl, ReportLab | Excel/PDF-Generierung |
| Container | Docker + Gunicorn | Production-ready |

### Ordnerstruktur

```
kreditkarten-app/
├── app.py                 # Flask-Anwendung
├── cli.py                 # CLI für Batch-Verarbeitung
├── matching.py            # Matching-Algorithmen
├── parsers/
│   ├── __init__.py
│   ├── csv_parser.py      # CSV-Import (verschiedene Banken)
│   ├── pdf_parser.py      # PDF-Statement-Parser
│   └── beleg_parser.py    # Beleg-Extraktion (von Spesen-App)
├── templates/
│   └── index.html         # Web-UI
├── static/                # CSS, JS (optional)
├── data/
│   ├── kreditkarten.db    # SQLite-Datenbank
│   └── .cache.json        # Verarbeitungs-Cache
├── imports/
│   ├── inbox/             # Neue Abrechnungen
│   └── archiv/            # Verarbeitete
├── belege/
│   ├── inbox/             # Neue Belege
│   └── archiv/            # Zugeordnete
├── exports/               # Generierte Reports
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Datenbank-Schema

```sql
-- Kreditkarten-Konten
CREATE TABLE konten (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- "Amex Gold", "Visa Business"
    kartennummer_encrypted TEXT,     -- Letzte 4 Ziffern verschlüsselt
    bank TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Monatliche Abrechnungen
CREATE TABLE abrechnungen (
    id INTEGER PRIMARY KEY,
    konto_id INTEGER REFERENCES konten(id),
    periode TEXT NOT NULL,           -- "Nov 2025"
    abrechnungsdatum DATE,
    gesamtbetrag REAL,
    status TEXT DEFAULT 'offen',     -- offen, in_bearbeitung, abgeschlossen
    file_hash TEXT,                  -- Original-Datei Hash
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(konto_id, periode)
);

-- Einzelne Transaktionen
CREATE TABLE transaktionen (
    id INTEGER PRIMARY KEY,
    abrechnung_id INTEGER REFERENCES abrechnungen(id),
    datum DATE NOT NULL,
    buchungsdatum DATE,
    beschreibung TEXT,               -- Original-Text von Kreditkarte
    haendler TEXT,                   -- Extrahierter Händlername
    betrag REAL NOT NULL,
    waehrung TEXT DEFAULT 'EUR',
    betrag_eur REAL,                 -- Umgerechnet
    kategorie TEXT,                  -- AI-kategorisiert
    kategorie_confidence REAL,       -- 0.0-1.0
    status TEXT DEFAULT 'offen',     -- offen, zugeordnet, manuell, ignoriert
    notizen TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Zugeordnete Belege
CREATE TABLE belege (
    id INTEGER PRIMARY KEY,
    transaktion_id INTEGER REFERENCES transaktionen(id),
    datei_name TEXT,
    datei_pfad TEXT,
    file_hash TEXT UNIQUE,
    extrahierte_daten TEXT,          -- JSON: Betrag, Datum, Händler
    match_confidence REAL,           -- 0.0-1.0
    match_typ TEXT,                  -- auto, manuell
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Kategorien mit Regeln
CREATE TABLE kategorie_regeln (
    id INTEGER PRIMARY KEY,
    kategorie TEXT NOT NULL,
    muster TEXT NOT NULL,            -- Regex oder Substring
    prioritaet INTEGER DEFAULT 0,
    aktiv BOOLEAN DEFAULT 1
);

-- Einstellungen
CREATE TABLE einstellungen (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT,
    firma TEXT,
    standard_kategorie TEXT DEFAULT 'Sonstiges',
    auto_kategorisieren BOOLEAN DEFAULT 1,
    auto_matching BOOLEAN DEFAULT 1
);
```

---

## Kategorien

```python
KATEGORIEN = {
    'bewirtung': 'Restaurants, Cafés, Bars',
    'reise_hotel': 'Hotels, Unterkünfte',
    'reise_flug': 'Flugtickets',
    'reise_bahn': 'Bahntickets',
    'reise_taxi': 'Taxi, Uber, Mietwagen',
    'buero': 'Bürobedarf, Schreibwaren',
    'software': 'Software, Abonnements, SaaS',
    'hardware': 'Computer, Geräte',
    'telefon': 'Telefon, Mobilfunk',
    'porto': 'Porto, Versand',
    'fachliteratur': 'Bücher, Zeitschriften',
    'fortbildung': 'Kurse, Konferenzen',
    'werbung': 'Marketing, Werbung',
    'versicherung': 'Versicherungen',
    'gebuehren': 'Bankgebühren, Kartengebühren',
    'privat': 'Private Ausgaben (nicht absetzbar)',
    'sonstiges': 'Sonstige Geschäftsausgaben'
}
```

---

## Workflow

### 1. Import Kreditkartenabrechnung

```
CSV/PDF Upload → Parser → Transaktionen extrahieren → DB speichern
                   ↓
              Claude AI → Händler normalisieren
                       → Kategorie vorschlagen
                       → Confidence Score
```

### 2. Belege zuordnen

```
Beleg Upload → OCR + Claude → Daten extrahieren (Betrag, Datum, Händler)
     ↓
Matching-Engine:
  1. Exakter Betrag + Datum ±3 Tage → Confidence 0.95
  2. Ähnlicher Händlername + Betrag → Confidence 0.80
  3. Nur Betrag passt → Confidence 0.50
     ↓
Vorschläge anzeigen → Benutzer bestätigt/korrigiert
```

### 3. Abgleich-Report

```
Abrechnung auswählen → Status-Übersicht:
  ✅ Zugeordnet: 45 Transaktionen (1.234,56 €)
  ⚠️  Offen: 3 Transaktionen (89,00 €)
  ❌ Ohne Beleg: 2 Transaktionen (45,00 €)
     ↓
Export: Excel mit allen Details + fehlende Belege markiert
        PDF-Zusammenfassung für Buchhaltung
        ZIP mit zugeordneten Belegen
```

---

## API-Endpoints

```python
# Konten
GET  /api/konten                    # Liste aller Kreditkarten
POST /api/konten                    # Neue Kreditkarte anlegen

# Abrechnungen
GET  /api/abrechnungen              # Liste aller Abrechnungen
POST /api/abrechnungen/import       # CSV/PDF importieren
GET  /api/abrechnungen/<id>         # Details einer Abrechnung

# Transaktionen
GET  /api/transaktionen?abrechnung_id=X
PUT  /api/transaktionen/<id>        # Kategorie/Status ändern
POST /api/transaktionen/<id>/beleg  # Beleg manuell zuordnen

# Belege
POST /api/belege/upload             # Beleg hochladen + AI-Parsing
GET  /api/belege/<id>               # Beleg anzeigen
POST /api/belege/match              # Auto-Matching starten

# Export
POST /export/excel                  # Excel-Export
POST /export/pdf                    # PDF-Report
POST /export/zip                    # Komplett-Paket

# Einstellungen
GET  /api/einstellungen
POST /api/einstellungen
GET  /api/kategorie-regeln
POST /api/kategorie-regeln
```

---

## CSV-Parser (Beispiel: Amex)

```python
# parsers/csv_parser.py

BANK_FORMATS = {
    'amex': {
        'encoding': 'utf-8',
        'delimiter': ',',
        'date_format': '%d.%m.%Y',
        'columns': {
            'datum': 'Datum',
            'beschreibung': 'Beschreibung',
            'betrag': 'Betrag',
            'waehrung': 'Fremdwährung'
        },
        'skip_rows': 0,
        'betrag_negativ': True  # Ausgaben sind negativ
    },
    'visa_dkb': {
        'encoding': 'iso-8859-1',
        'delimiter': ';',
        'date_format': '%d.%m.%y',
        'columns': {
            'datum': 'Belegdatum',
            'buchungsdatum': 'Wertstellung',
            'beschreibung': 'Beschreibung',
            'betrag': 'Betrag (EUR)',
        },
        'skip_rows': 6,
        'betrag_negativ': False
    }
}

def parse_csv(file_content, bank_format='amex'):
    config = BANK_FORMATS[bank_format]
    # ... Parsing-Logik
    return transaktionen
```

---

## Matching-Algorithmus

```python
# matching.py

from difflib import SequenceMatcher
from datetime import timedelta

def find_matches(transaktion, belege, threshold=0.5):
    """Findet passende Belege für eine Transaktion."""
    matches = []

    for beleg in belege:
        score = 0.0

        # Betrag-Match (wichtigster Faktor)
        if abs(transaktion.betrag - beleg.betrag) < 0.01:
            score += 0.5
        elif abs(transaktion.betrag - beleg.betrag) < 1.0:
            score += 0.3

        # Datum-Match
        tage_diff = abs((transaktion.datum - beleg.datum).days)
        if tage_diff == 0:
            score += 0.3
        elif tage_diff <= 3:
            score += 0.2
        elif tage_diff <= 7:
            score += 0.1

        # Händler-Match (Fuzzy)
        if transaktion.haendler and beleg.haendler:
            similarity = SequenceMatcher(
                None,
                transaktion.haendler.lower(),
                beleg.haendler.lower()
            ).ratio()
            score += similarity * 0.2

        if score >= threshold:
            matches.append({
                'beleg': beleg,
                'confidence': min(score, 1.0),
                'match_details': {
                    'betrag_match': abs(transaktion.betrag - beleg.betrag) < 0.01,
                    'datum_diff': tage_diff,
                    'haendler_similarity': similarity if transaktion.haendler else 0
                }
            })

    return sorted(matches, key=lambda x: x['confidence'], reverse=True)
```

---

## Claude AI Prompts

### Transaktions-Kategorisierung

```python
KATEGORISIERUNG_PROMPT = """
Analysiere diese Kreditkarten-Transaktion und kategorisiere sie.

Transaktion:
- Datum: {datum}
- Beschreibung: {beschreibung}
- Betrag: {betrag} {waehrung}

Verfügbare Kategorien:
{kategorien_liste}

Antworte NUR mit JSON:
{{
    "haendler": "Normalisierter Händlername",
    "kategorie": "kategorie_key",
    "confidence": 0.0-1.0,
    "geschaeftlich": true/false,
    "notiz": "Optional: Kurze Erklärung"
}}
"""
```

### Beleg-Extraktion

```python
BELEG_EXTRAKTION_PROMPT = """
Extrahiere die folgenden Informationen aus diesem Beleg/Rechnung:

{ocr_text}

Antworte NUR mit JSON:
{{
    "haendler": "Name des Geschäfts/Restaurants",
    "adresse": "Adresse falls vorhanden",
    "datum": "TT.MM.JJJJ",
    "betrag": 123.45,
    "waehrung": "EUR",
    "mwst": 12.34,
    "zahlungsart": "Kreditkarte/Bar/EC",
    "rechnungsnummer": "Falls vorhanden"
}}
"""
```

---

## Wiederverwendbare Komponenten aus Spesen-App

### Direkt übernehmen (Copy & Adapt)

| Datei | Komponente | Anpassung |
|-------|------------|-----------|
| `app.py` | Flask-Grundgerüst | Routen anpassen |
| `app.py` | `get_anthropic_client()` | Unverändert |
| `app.py` | `extract_receipt_data_with_ai()` | Prompt anpassen |
| `app.py` | Encryption (Fernet) | Unverändert |
| `app.py` | `generate_pdf_buffer()` | Layout anpassen |
| `app.py` | Excel-Export Styling | Spalten anpassen |
| `app.py` | ZIP-Export | Struktur anpassen |
| `app.py` | `parse_monat_string()` | Unverändert |
| `app.py` | `sort_expenses_by_date()` | Umbenennen |
| `cli.py` | Cache-Management | Unverändert |
| `cli.py` | Währungsumrechnung (EZB) | Unverändert |
| `templates/index.html` | Navbar, Modals | Inhalte anpassen |
| `templates/index.html` | PDF-Viewer | Unverändert |
| `templates/index.html` | File Upload | Unverändert |
| `Dockerfile` | Multi-Stage Build | Unverändert |
| `docker-compose.yml` | Traefik Setup | Ports/Namen anpassen |
| `gunicorn.conf.py` | WSGI Config | Unverändert |

### Neue Komponenten

| Komponente | Beschreibung |
|------------|--------------|
| `parsers/csv_parser.py` | Bank-spezifische CSV-Parser |
| `parsers/pdf_parser.py` | PDF-Statement-Extraktion |
| `matching.py` | Beleg-Transaktion-Matching |
| `kategorisierung.py` | Regel-basierte + AI-Kategorisierung |
| `reports.py` | Abgleich-Reports |

---

## UI-Mockup

```
┌─────────────────────────────────────────────────────────────────┐
│ 💳 Kreditkarten-Abgleich                    [Einstellungen] [?] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Konto: [Amex Gold ▼]     Periode: [Nov 2025 ▼]    [Import ▲]  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Übersicht                                    Export [▼] │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │  Gesamt: 2.456,78 €    Transaktionen: 48               │   │
│  │  ✅ Zugeordnet: 42     ⚠️ Offen: 4     ❌ Ohne Beleg: 2 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ▼ Bewirtung (8)                               Summe: 456,00 € │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ [5] 12.11. Restaurant Gentorellis      110,00 € ✅ [👁] │   │
│  │ [6] 19.11. Cantina Divino              118,70 € ✅ [👁] │   │
│  │ [7] 20.11. RESTAURANT HAMBURG           43,00 € ⚠️ [+] │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ▶ Reise & Transport (15)                      Summe: 890,00 € │
│  ▶ Software & Abos (8)                         Summe: 234,50 € │
│  ▶ Sonstiges (17)                              Summe: 876,28 € │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📄 Belege hochladen                    [Drag & Drop]    │   │
│  │                                                         │   │
│  │  Unzugeordnete Belege: 3                               │   │
│  │  • Rechnung_2025-11-15.pdf (45,00 €)         [Zuordnen]│   │
│  │  • Quittung_Restaurant.jpg (23,50 €)         [Zuordnen]│   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementierungs-Reihenfolge

### Phase 1: Grundgerüst (Tag 1-2)
- [ ] Projekt-Setup (Ordner, venv, Docker)
- [ ] Datenbank-Schema erstellen
- [ ] Flask-App mit Basis-Routen
- [ ] Einfaches Frontend (Materialize)

### Phase 2: Import (Tag 3-4)
- [ ] CSV-Parser für Amex
- [ ] Transaktionen in DB speichern
- [ ] Transaktions-Liste anzeigen

### Phase 3: Kategorisierung (Tag 5-6)
- [ ] Regel-basierte Kategorisierung
- [ ] Claude AI Integration
- [ ] Manuelle Kategorie-Änderung

### Phase 4: Beleg-Zuordnung (Tag 7-9)
- [ ] Beleg-Upload + AI-Extraktion
- [ ] Matching-Algorithmus
- [ ] Zuordnungs-UI

### Phase 5: Export & Reports (Tag 10-11)
- [ ] Excel-Export mit Status
- [ ] PDF-Zusammenfassung
- [ ] ZIP-Bundle

### Phase 6: Polish (Tag 12-14)
- [ ] Weitere Bank-Formate
- [ ] Bulk-Aktionen
- [ ] Tests
- [ ] Dokumentation

---

## Offene Fragen

1. **Welche Kreditkarten/Banken?**
   - Amex, Visa, Mastercard?
   - Welche Banken (DKB, Comdirect, ...)?

2. **CSV-Format oder PDF?**
   - Die meisten Banken bieten CSV-Export
   - PDF ist komplexer zu parsen

3. **Integration mit Spesen-App?**
   - Gemeinsame Beleg-Datenbank?
   - Oder komplett getrennt?

4. **Buchhaltungs-Export?**
   - DATEV-Format benötigt?
   - Kontierung gewünscht?

---

## Referenz-Dateien

Im ZIP-Archiv enthalten:
- `app.py` - Komplette Spesen-App als Referenz
- `cli.py` - CLI-Tool mit Batch-Verarbeitung
- `templates/index.html` - Frontend-Template
- `Dockerfile` - Docker-Setup
- `docker-compose.yml` - Container-Orchestrierung
- `requirements.txt` - Python-Dependencies
