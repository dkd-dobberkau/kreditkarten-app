"""
CSV Parser für verschiedene Kreditkarten-Abrechnungen
"""

import csv
import re
from datetime import datetime
from io import StringIO

# Bank-spezifische Formate
BANK_FORMATS = {
    'amex': {
        'encoding': 'utf-8',
        'delimiter': ',',
        'date_format': '%d.%m.%Y',
        'columns': {
            'datum': ['Datum', 'Date', 'Transaktionsdatum'],
            'beschreibung': ['Beschreibung', 'Description', 'Verwendungszweck'],
            'betrag': ['Betrag', 'Amount', 'Umsatz'],
            'waehrung': ['Fremdwährung', 'Currency', 'Währung']
        },
        'skip_rows': 0,
        'betrag_negativ': True,  # Ausgaben sind negativ
        'decimal_separator': ',',
        'thousands_separator': '.'
    },
    'visa_dkb': {
        'encoding': 'iso-8859-1',
        'delimiter': ';',
        'date_format': '%d.%m.%y',
        'columns': {
            'datum': ['Belegdatum', 'Umsatz abgerechnet und nicht im Saldo enthalten'],
            'buchungsdatum': ['Wertstellung'],
            'beschreibung': ['Beschreibung'],
            'betrag': ['Betrag (EUR)', 'Betrag'],
        },
        'skip_rows': 6,
        'betrag_negativ': False,
        'decimal_separator': ',',
        'thousands_separator': '.'
    },
    'mastercard_sparkasse': {
        'encoding': 'iso-8859-1',
        'delimiter': ';',
        'date_format': '%d.%m.%Y',
        'columns': {
            'datum': ['Buchungstag', 'Belegdatum'],
            'buchungsdatum': ['Valuta'],
            'beschreibung': ['Verwendungszweck', 'Buchungstext'],
            'betrag': ['Umsatz', 'Betrag'],
        },
        'skip_rows': 0,
        'betrag_negativ': False,
        'decimal_separator': ',',
        'thousands_separator': '.'
    },
    'generic': {
        'encoding': 'utf-8',
        'delimiter': ',',
        'date_format': '%Y-%m-%d',
        'columns': {
            'datum': ['date', 'datum', 'Date', 'Datum'],
            'beschreibung': ['description', 'beschreibung', 'Description', 'Beschreibung'],
            'betrag': ['amount', 'betrag', 'Amount', 'Betrag'],
        },
        'skip_rows': 0,
        'betrag_negativ': False,
        'decimal_separator': '.',
        'thousands_separator': ','
    }
}


def detect_bank_format(content):
    """Erkennt das Bank-Format anhand des CSV-Inhalts."""
    content_lower = content.lower()

    # Amex-spezifische Marker
    if 'american express' in content_lower or 'amex' in content_lower:
        return 'amex'

    # DKB-spezifische Marker
    if 'dkb' in content_lower or 'deutsche kreditbank' in content_lower:
        return 'visa_dkb'

    # Sparkasse-spezifische Marker
    if 'sparkasse' in content_lower:
        return 'mastercard_sparkasse'

    # Versuche anhand der Spalten zu erkennen
    first_lines = content.split('\n')[:10]

    for line in first_lines:
        if 'Belegdatum' in line and ';' in line:
            return 'visa_dkb'
        if 'Buchungstag' in line and ';' in line:
            return 'mastercard_sparkasse'

    # Semikolon = wahrscheinlich deutsches Format
    if ';' in content[:500]:
        return 'visa_dkb'

    return 'generic'


def parse_amount(amount_str, config):
    """Parst einen Betrag-String in eine Zahl."""
    if not amount_str:
        return 0.0

    amount_str = str(amount_str).strip()

    # Entferne Währungssymbole
    amount_str = re.sub(r'[€$£CHF\s]', '', amount_str)

    # Handle deutsche Zahlenformate (1.234,56)
    if config.get('decimal_separator') == ',':
        amount_str = amount_str.replace('.', '').replace(',', '.')

    try:
        return float(amount_str)
    except ValueError:
        return 0.0


def parse_date(date_str, date_format):
    """Parst einen Datum-String."""
    if not date_str:
        return None

    date_str = str(date_str).strip()

    # Verschiedene Formate versuchen
    formats = [
        date_format,
        '%d.%m.%Y',
        '%d.%m.%y',
        '%Y-%m-%d',
        '%d/%m/%Y',
        '%m/%d/%Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue

    return None


def find_column(headers, column_names):
    """Findet die Spalten-Nummer für einen Spaltennamen."""
    headers_lower = [h.lower().strip() for h in headers]

    for name in column_names:
        name_lower = name.lower()
        for i, header in enumerate(headers_lower):
            if name_lower in header or header in name_lower:
                return i

    return None


def parse_csv(content, bank_format='generic'):
    """Parst CSV-Inhalt und gibt Liste von Transaktionen zurück."""
    config = BANK_FORMATS.get(bank_format, BANK_FORMATS['generic'])

    # Zeilen überspringen
    lines = content.split('\n')
    skip = config.get('skip_rows', 0)

    # Finde die Header-Zeile (erste nicht-leere Zeile nach skip)
    header_idx = skip
    while header_idx < len(lines) and not lines[header_idx].strip():
        header_idx += 1

    if header_idx >= len(lines):
        return []

    # Parse CSV
    csv_content = '\n'.join(lines[header_idx:])
    reader = csv.reader(
        StringIO(csv_content),
        delimiter=config.get('delimiter', ','),
        quotechar='"'
    )

    try:
        headers = next(reader)
    except StopIteration:
        return []

    # Spalten-Mapping
    col_config = config.get('columns', {})
    col_indices = {}

    for field, names in col_config.items():
        idx = find_column(headers, names)
        if idx is not None:
            col_indices[field] = idx

    if 'datum' not in col_indices or 'betrag' not in col_indices:
        # Versuche einfache Zuordnung nach Position
        if len(headers) >= 3:
            col_indices = {'datum': 0, 'beschreibung': 1, 'betrag': 2}
        else:
            return []

    transaktionen = []

    for row in reader:
        if not row or len(row) <= max(col_indices.values()):
            continue

        # Prüfe ob Zeile Daten enthält (nicht nur Header oder Fußzeile)
        datum_raw = row[col_indices['datum']] if 'datum' in col_indices else ''
        if not datum_raw or datum_raw == headers[col_indices['datum']]:
            continue

        datum = parse_date(datum_raw, config.get('date_format', '%Y-%m-%d'))
        if not datum:
            continue

        betrag = parse_amount(
            row[col_indices['betrag']] if 'betrag' in col_indices else '0',
            config
        )

        # Bei manchen Banken sind Ausgaben negativ
        if config.get('betrag_negativ') and betrag < 0:
            betrag = abs(betrag)

        beschreibung = ''
        if 'beschreibung' in col_indices:
            beschreibung = row[col_indices['beschreibung']].strip()

        buchungsdatum = None
        if 'buchungsdatum' in col_indices:
            buchungsdatum = parse_date(
                row[col_indices['buchungsdatum']],
                config.get('date_format', '%Y-%m-%d')
            )

        waehrung = 'EUR'
        if 'waehrung' in col_indices and row[col_indices['waehrung']]:
            waehrung = row[col_indices['waehrung']].strip().upper()
            if not waehrung:
                waehrung = 'EUR'

        transaktionen.append({
            'datum': datum,
            'buchungsdatum': buchungsdatum,
            'beschreibung': beschreibung,
            'betrag': betrag,
            'waehrung': waehrung,
            'betrag_eur': betrag if waehrung == 'EUR' else None
        })

    return transaktionen
