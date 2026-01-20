"""
Beleg-Parser für Quittungen und Rechnungen
Extrahiert Daten mittels OCR und Claude AI
"""

import os
import json
import base64
from datetime import datetime

# Optional imports
try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    from pdf2image import convert_from_path
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


def validate_file_path(filepath, allowed_extensions=None):
    """
    Validate and normalize file path to prevent path traversal attacks.
    Returns normalized absolute path or raises ValueError.
    """
    if not filepath:
        raise ValueError("Dateipfad darf nicht leer sein")

    # Normalize path (resolve .., symlinks, etc.)
    normalized = os.path.normpath(os.path.realpath(filepath))

    # Check if file exists
    if not os.path.isfile(normalized):
        raise ValueError(f"Datei nicht gefunden: {filepath}")

    # Validate extension if specified
    if allowed_extensions:
        ext = os.path.splitext(normalized)[1].lower()
        if ext not in allowed_extensions:
            raise ValueError(f"Nicht erlaubte Dateiendung: {ext}")

    return normalized


def image_to_base64(image_path):
    """Convert image file to base64 string."""
    # Validate path before opening
    safe_path = validate_file_path(image_path, {'.jpg', '.jpeg', '.png', '.gif', '.webp'})
    with open(safe_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def get_media_type(filepath):
    """Get media type from file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    return media_types.get(ext, 'image/jpeg')


def ocr_image(image_path):
    """Extract text from image using OCR."""
    if not OCR_AVAILABLE:
        return ""

    try:
        image = Image.open(image_path)
        # Deutsch + Englisch für OCR
        text = pytesseract.image_to_string(image, lang='deu+eng')
        return text.strip()
    except Exception as e:
        print(f"OCR Fehler: {e}")
        return ""


def pdf_to_images(pdf_path):
    """Convert PDF to list of images."""
    if not PDF_SUPPORT:
        return []

    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=3)
        return images
    except Exception as e:
        print(f"PDF Konvertierung Fehler: {e}")
        return []


def extract_with_ai(image_path=None, ocr_text=None, image_base64=None, media_type=None):
    """Extract receipt data using Claude AI."""
    if not AI_AVAILABLE:
        return None

    try:
        client = get_anthropic_client()

        prompt = """Extrahiere die folgenden Informationen aus diesem Beleg/Rechnung.

Antworte NUR mit JSON (keine Erklärungen):
{
    "haendler": "Name des Geschäfts/Restaurants",
    "adresse": "Adresse falls vorhanden oder null",
    "datum": "TT.MM.JJJJ oder null",
    "betrag": 123.45,
    "waehrung": "EUR",
    "mwst": 12.34,
    "zahlungsart": "Kreditkarte/Bar/EC/null",
    "rechnungsnummer": "Falls vorhanden oder null",
    "kategorie_vorschlag": "bewirtung/reise_hotel/buero/software/sonstiges"
}

Falls ein Wert nicht erkennbar ist, setze null."""

        content = []

        # Add image if available
        if image_base64:
            # Determine media type
            if not media_type:
                media_type = get_media_type(image_path) if image_path else "image/png"
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_base64
                }
            })
        elif image_path and os.path.exists(image_path):
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": get_media_type(image_path),
                    "data": image_to_base64(image_path)
                }
            })

        # Add OCR text as context
        if ocr_text:
            prompt += f"\n\nOCR-Text des Belegs:\n{ocr_text}"

        content.append({"type": "text", "text": prompt})

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": content}]
        )

        response_text = message.content[0].text

        # Extract JSON from response
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0]

        return json.loads(response_text.strip())

    except Exception as e:
        print(f"AI Extraktion Fehler: {e}")
        return None


def extract_beleg_data(filepath):
    """
    Extrahiert Daten aus einem Beleg (Bild oder PDF).

    Returns:
        dict mit extrahierten Daten
    """
    result = {
        'haendler': None,
        'datum': None,
        'betrag': None,
        'waehrung': 'EUR',
        'mwst': None,
        'kategorie_vorschlag': 'sonstiges',
        'ocr_text': None,
        'confidence': 0.0
    }

    # Validate path to prevent path traversal
    allowed_ext = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp'}
    try:
        safe_filepath = validate_file_path(filepath, allowed_ext)
    except ValueError:
        return result

    ext = os.path.splitext(safe_filepath)[1].lower()
    ocr_text = ""
    image_base64 = None

    # Handle PDFs
    if ext == '.pdf':
        if PDF_SUPPORT:
            images = pdf_to_images(safe_filepath)
            if images:
                # OCR auf erste Seite
                import io
                img_byte_arr = io.BytesIO()
                images[0].save(img_byte_arr, format='PNG')
                img_byte_arr.seek(0)
                image_base64 = base64.b64encode(img_byte_arr.read()).decode('utf-8')

                if OCR_AVAILABLE:
                    ocr_text = pytesseract.image_to_string(images[0], lang='deu+eng')
    else:
        # Image file
        if OCR_AVAILABLE:
            ocr_text = ocr_image(safe_filepath)
        image_base64 = image_to_base64(safe_filepath)

    result['ocr_text'] = ocr_text[:2000] if ocr_text else None

    # Try AI extraction
    if AI_AVAILABLE and (image_base64 or ocr_text):
        # For PDFs, we converted to PNG
        pdf_media_type = "image/png" if ext == '.pdf' else None
        ai_result = extract_with_ai(
            image_path=filepath if ext != '.pdf' else None,
            ocr_text=ocr_text,
            image_base64=image_base64,
            media_type=pdf_media_type
        )

        if ai_result:
            result.update({
                'haendler': ai_result.get('haendler'),
                'datum': ai_result.get('datum'),
                'betrag': ai_result.get('betrag'),
                'waehrung': ai_result.get('waehrung', 'EUR'),
                'mwst': ai_result.get('mwst'),
                'kategorie_vorschlag': ai_result.get('kategorie_vorschlag', 'sonstiges'),
                'adresse': ai_result.get('adresse'),
                'rechnungsnummer': ai_result.get('rechnungsnummer'),
                'zahlungsart': ai_result.get('zahlungsart'),
                'confidence': 0.85  # AI extraction confidence
            })

    # Fallback: Try to extract from OCR text
    elif ocr_text:
        result.update(extract_from_ocr(ocr_text))

    return result


def extract_from_ocr(text):
    """Fallback extraction from OCR text without AI."""
    import re

    result = {
        'confidence': 0.3
    }

    # Betrag suchen (verschiedene Formate)
    betrag_patterns = [
        r'(?:Summe|Total|Gesamt|Betrag|EUR|€)\s*:?\s*([\d.,]+)',
        r'([\d]+[,.][\d]{2})\s*(?:EUR|€)',
        r'(?:zu zahlen|Endbetrag)\s*:?\s*([\d.,]+)',
    ]

    for pattern in betrag_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            betrag_str = match.group(1).replace('.', '').replace(',', '.')
            try:
                result['betrag'] = float(betrag_str)
                break
            except ValueError:
                pass

    # Datum suchen
    datum_patterns = [
        r'(\d{2})[./](\d{2})[./](\d{4})',
        r'(\d{2})[./](\d{2})[./](\d{2})',
    ]

    for pattern in datum_patterns:
        match = re.search(pattern, text)
        if match:
            day, month, year = match.groups()
            if len(year) == 2:
                year = '20' + year
            result['datum'] = f"{day}.{month}.{year}"
            break

    return result
