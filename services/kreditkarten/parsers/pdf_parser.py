"""
PDF Parser für Kreditkarten-Abrechnungen
Unterstützt: American Express Business Card (Deutschland)
"""

import re
import os
from datetime import datetime

# Optional imports
try:
    from pdf2image import convert_from_path
    import pytesseract
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

try:
    import anthropic
    from dotenv import load_dotenv
    load_dotenv()
    AI_AVAILABLE = bool(os.environ.get('ANTHROPIC_API_KEY'))
except ImportError:
    AI_AVAILABLE = False


def get_anthropic_client():
    """Get Anthropic API client."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def validate_pdf_path(pdf_path):
    """
    Validate and normalize PDF path to prevent path traversal attacks.
    Returns normalized absolute path or raises ValueError.
    """
    if not pdf_path:
        raise ValueError("PDF-Pfad darf nicht leer sein")

    # Normalize path (resolve .., symlinks, etc.)
    normalized = os.path.normpath(os.path.realpath(pdf_path))

    # Check if file exists and is a PDF
    if not os.path.isfile(normalized):
        raise ValueError(f"PDF nicht gefunden: {pdf_path}")

    if not normalized.lower().endswith('.pdf'):
        raise ValueError("Nur PDF-Dateien erlaubt")

    return normalized


def extract_text_from_pdf(pdf_path):
    """Extrahiert Text aus PDF mittels OCR."""
    if not PDF_SUPPORT:
        raise RuntimeError("pdf2image/pytesseract nicht installiert")

    safe_path = validate_pdf_path(pdf_path)
    images = convert_from_path(safe_path)
    text_pages = []

    for image in images:
        text = pytesseract.image_to_string(image, lang='deu+eng')
        text_pages.append(text)

    return text_pages


def parse_amex_business_with_ai(pdf_path):
    """
    Parst Amex Business Card PDF mit Claude AI.
    Extrahiert alle Transaktionen strukturiert.
    """
    if not AI_AVAILABLE:
        raise RuntimeError("ANTHROPIC_API_KEY nicht gesetzt")

    import base64

    # Validate and normalize path
    safe_path = validate_pdf_path(pdf_path)

    # PDF in Bilder konvertieren
    if not PDF_SUPPORT:
        raise RuntimeError("pdf2image nicht installiert")

    images = convert_from_path(safe_path)
    client = get_anthropic_client()

    all_transactions = []
    periode = None
    gesamtbetrag = None

    # Jede Seite analysieren
    for i, image in enumerate(images):
        # Bild zu Base64
        import io
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        image_base64 = base64.b64encode(img_byte_arr.read()).decode('utf-8')

        prompt = """Analysiere diese Amex Kreditkartenabrechnung und extrahiere ALLE Transaktionen.

Für jede Transaktion extrahiere:
- umsatz_vom: Datum im Format TT.MM (z.B. "24.10")
- buchungsdatum: Datum im Format TT.MM (z.B. "24.10")
- beschreibung: Vollständiger Händlername und Ort (z.B. "MOTEL ONE GERMANY BETRI MÜNCHEN")
- betrag_eur: Betrag in EUR als Zahl (z.B. 150.00)
- betrag_fremdwaehrung: Falls vorhanden, Betrag in Fremdwährung als Zahl
- waehrung: Falls Fremdwährung, die Währung (z.B. "USD", "DKK")
- ist_gutschrift: true wenn GUTSCHRIFT, sonst false

Ignoriere:
- Zahlungen/Überweisungen ("ZAHLUNG/ÜBERWEISUNG ERHALTEN")
- Kopfzeilen, Fußzeilen, Hinweistexte
- Membership Rewards Informationen

Extrahiere auch:
- periode: Abrechnungszeitraum (z.B. "24.10.25 bis 23.11.25")
- gesamtbetrag: "Saldo des laufenden Monats" oder "Neuer Saldo" in EUR

Antworte NUR mit JSON:
{
    "periode": "24.10.25 bis 23.11.25",
    "gesamtbetrag": 8600.67,
    "transaktionen": [
        {
            "umsatz_vom": "24.10",
            "buchungsdatum": "24.10",
            "beschreibung": "MOTEL ONE GERMANY BETRI MÜNCHEN",
            "betrag_eur": 150.00,
            "betrag_fremdwaehrung": null,
            "waehrung": "EUR",
            "ist_gutschrift": false
        }
    ]
}"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        )

        response_text = message.content[0].text

        # JSON extrahieren
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0]

        import json
        try:
            data = json.loads(response_text.strip())

            if data.get('periode') and not periode:
                periode = data['periode']
            if data.get('gesamtbetrag') and not gesamtbetrag:
                gesamtbetrag = data['gesamtbetrag']

            for t in data.get('transaktionen', []):
                all_transactions.append(t)

        except json.JSONDecodeError as e:
            print(f"JSON Parse Error auf Seite {i+1}: {e}")
            continue

    # Duplikate entfernen (basierend auf Datum + Beschreibung + Betrag)
    seen = set()
    unique_transactions = []
    for t in all_transactions:
        key = (t.get('umsatz_vom'), t.get('beschreibung'), t.get('betrag_eur'))
        if key not in seen:
            seen.add(key)
            unique_transactions.append(t)

    return {
        'periode': periode,
        'gesamtbetrag': gesamtbetrag,
        'transaktionen': unique_transactions
    }


def convert_to_standard_format(amex_data, year=None):
    """
    Konvertiert Amex-Daten ins Standard-Format für die App.
    """
    if not year:
        year = datetime.now().year

    transaktionen = []

    for t in amex_data.get('transaktionen', []):
        # Datum parsen (TT.MM -> YYYY-MM-DD)
        umsatz_vom = t.get('umsatz_vom', '')
        if umsatz_vom:
            try:
                day, month = umsatz_vom.split('.')
                # Jahr bestimmen (bei Jahreswechsel)
                datum = f"{year}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                datum = None
        else:
            datum = None

        buchungsdatum = t.get('buchungsdatum', '')
        if buchungsdatum:
            try:
                day, month = buchungsdatum.split('.')
                buchungsdatum = f"{year}-{int(month):02d}-{int(day):02d}"
            except ValueError:
                buchungsdatum = None

        betrag = t.get('betrag_eur', 0)
        ist_gutschrift = t.get('ist_gutschrift', False)

        # Gutschriften als negative Beträge speichern
        if ist_gutschrift:
            betrag = -abs(betrag)
        else:
            betrag = abs(betrag)

        transaktionen.append({
            'datum': datum,
            'buchungsdatum': buchungsdatum,
            'beschreibung': t.get('beschreibung', ''),
            'betrag': betrag,
            'waehrung': t.get('waehrung', 'EUR'),
            'betrag_eur': betrag,
            'betrag_fremdwaehrung': t.get('betrag_fremdwaehrung'),
            'ist_gutschrift': ist_gutschrift
        })

    return transaktionen


def parse_amex_pdf(pdf_path, year=None):
    """
    Hauptfunktion zum Parsen einer Amex Business Card PDF.

    Args:
        pdf_path: Pfad zur PDF-Datei
        year: Jahr für Datumskonvertierung (default: aktuelles Jahr)

    Returns:
        dict mit 'periode', 'gesamtbetrag', 'transaktionen'
    """
    # Validate path (prevents path traversal)
    safe_path = validate_pdf_path(pdf_path)

    # Mit AI parsen (safe_path wird erneut validiert, das ist OK)
    amex_data = parse_amex_business_with_ai(safe_path)

    # Jahr aus Periode extrahieren falls möglich
    if not year and amex_data.get('periode'):
        match = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', amex_data['periode'])
        if match:
            y = match.group(3)
            year = int(y) if len(y) == 4 else 2000 + int(y)

    # Ins Standard-Format konvertieren
    transaktionen = convert_to_standard_format(amex_data, year)

    return {
        'periode': amex_data.get('periode'),
        'gesamtbetrag': amex_data.get('gesamtbetrag'),
        'transaktionen': transaktionen
    }


# Für direkte Ausführung / Test
if __name__ == '__main__':
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    result = parse_amex_pdf(pdf_path)

    print(f"Periode: {result['periode']}")
    print(f"Gesamtbetrag: {result['gesamtbetrag']} EUR")
    print(f"Transaktionen: {len(result['transaktionen'])}")
    print()

    for t in result['transaktionen']:
        gutschrift = " (GUTSCHRIFT)" if t.get('ist_gutschrift') else ""
        print(f"  {t['datum']} | {t['beschreibung'][:40]:<40} | {t['betrag_eur']:>10.2f} EUR{gutschrift}")
