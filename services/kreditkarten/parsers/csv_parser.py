"""
CSV Parser für verschiedene Kreditkarten-Abrechnungen
"""

import csv
import re
from datetime import datetime, timedelta
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


def validate_transaktionen(transaktionen, periode=None):
    """
    Validiert Transaktionen und erkennt systematische Datumsfehler.

    Returns:
        dict mit:
        - valid: bool - ob die Daten gültig sind
        - warnings: list - Warnungen
        - corrections: dict - Vorgeschlagene Korrekturen
        - transaktionen: list - korrigierte Transaktionen (wenn auto_correct)
    """
    if not transaktionen:
        return {'valid': True, 'warnings': [], 'corrections': {}, 'transaktionen': []}

    warnings = []
    corrections = {}
    heute = datetime.now().date()

    # Sammle alle Transaktionsdaten
    future_dates = []
    date_years = {}

    for idx, t in enumerate(transaktionen):
        datum_str = t.get('datum')
        if not datum_str:
            continue

        try:
            datum = datetime.strptime(datum_str, '%Y-%m-%d').date()
        except ValueError:
            continue

        # Prüfe auf Zukunftsdaten
        if datum > heute:
            future_dates.append({
                'index': idx,
                'datum': datum_str,
                'beschreibung': t.get('beschreibung', '')[:50]
            })

        # Zähle Jahre
        year = datum.year
        if year not in date_years:
            date_years[year] = []
        date_years[year].append(idx)

    # Parse Periode für Jahresvergleich
    periode_year = None
    if periode:
        try:
            parts = periode.split()
            if len(parts) >= 2:
                periode_year = int(parts[-1])
        except (ValueError, IndexError):
            pass

    # Analysiere Jahresverteilung
    sorted_years = sorted(date_years.keys())

    for year in sorted_years:
        count = len(date_years[year])
        total = len(transaktionen)

        # Prüfe auf systematischen Jahresfehler
        is_year_error = False
        expected_year = None

        # Fall 1: Transaktionen in der Zukunft
        if year > heute.year:
            is_year_error = True
            expected_year = year - 1

        # Fall 2: Transaktionen ein Jahr nach der Periode
        elif periode_year and year == periode_year + 1:
            is_year_error = True
            expected_year = periode_year

        if is_year_error and expected_year:
            if count == total:
                # Alle Transaktionen im falschen Jahr
                warnings.append({
                    'type': 'year_error',
                    'severity': 'error',
                    'message': f'Alle {count} Transaktionen haben das Jahr {year}, erwartet wird {expected_year}',
                    'auto_correctable': True
                })
                corrections['year_shift'] = {
                    'from': year,
                    'to': expected_year,
                    'affected_count': count
                }
            elif count > total * 0.5:
                # Mehr als 50% im falschen Jahr
                warnings.append({
                    'type': 'year_error',
                    'severity': 'warning',
                    'message': f'{count} von {total} Transaktionen haben das Jahr {year}, möglicherweise sollte es {expected_year} sein',
                    'auto_correctable': True
                })
                corrections['year_shift'] = {
                    'from': year,
                    'to': expected_year,
                    'affected_count': count
                }

    # Einzelne Zukunftsdaten (ohne systematischen Fehler)
    if future_dates and 'year_shift' not in corrections:
        if len(future_dates) <= 3:
            for fd in future_dates:
                warnings.append({
                    'type': 'future_date',
                    'severity': 'warning',
                    'message': f'Transaktion "{fd["beschreibung"]}" hat Datum in der Zukunft: {fd["datum"]}',
                    'auto_correctable': False
                })
        else:
            warnings.append({
                'type': 'future_dates',
                'severity': 'warning',
                'message': f'{len(future_dates)} Transaktionen haben Datum in der Zukunft',
                'auto_correctable': False
            })

    # Prüfe Konsistenz mit Periode
    if periode:
        try:
            # Parse Periode (z.B. "Dezember 2025")
            monat_namen = {
                'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
                'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
                'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12
            }
            parts = periode.lower().split()
            if len(parts) >= 2:
                monat = monat_namen.get(parts[0])
                jahr = int(parts[1])

                if monat and jahr:
                    periode_start = datetime(jahr, monat, 1).date()
                    periode_end = datetime(jahr, monat + 1 if monat < 12 else 1, 1).date() - timedelta(days=1)
                    if monat == 12:
                        periode_end = datetime(jahr, 12, 31).date()

                    outside_periode = 0
                    for t in transaktionen:
                        datum_str = t.get('datum')
                        if datum_str:
                            try:
                                datum = datetime.strptime(datum_str, '%Y-%m-%d').date()
                                # Erlaube 7 Tage Toleranz
                                if datum < periode_start - timedelta(days=7) or datum > periode_end + timedelta(days=7):
                                    outside_periode += 1
                            except ValueError:
                                pass

                    if outside_periode > 0:
                        warnings.append({
                            'type': 'periode_mismatch',
                            'severity': 'info',
                            'message': f'{outside_periode} Transaktionen liegen außerhalb der Periode {periode}',
                            'auto_correctable': False
                        })
        except (ValueError, IndexError):
            pass

    valid = not any(w.get('severity') == 'error' for w in warnings)

    return {
        'valid': valid,
        'warnings': warnings,
        'corrections': corrections,
        'transaktionen': transaktionen
    }


def apply_corrections(transaktionen, corrections):
    """
    Wendet Korrekturen auf Transaktionen an.

    Returns:
        list: korrigierte Transaktionen
    """
    if not corrections:
        return transaktionen

    corrected = []

    for t in transaktionen:
        t_copy = t.copy()

        # Jahreskorrektur
        if 'year_shift' in corrections:
            datum_str = t_copy.get('datum')
            if datum_str:
                from_year = str(corrections['year_shift']['from'])
                to_year = str(corrections['year_shift']['to'])
                if datum_str.startswith(from_year):
                    t_copy['datum'] = to_year + datum_str[4:]

            # Auch Buchungsdatum korrigieren
            buchungsdatum_str = t_copy.get('buchungsdatum')
            if buchungsdatum_str:
                if buchungsdatum_str.startswith(from_year):
                    t_copy['buchungsdatum'] = to_year + buchungsdatum_str[4:]

        corrected.append(t_copy)

    return corrected
