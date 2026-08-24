"""
Matching-Algorithmus für Beleg-Transaktions-Zuordnung
"""

from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re


# Plausible Bandbreite des impliziten Umrechnungskurses (EUR je Fremdwährungseinheit).
# Wird geprüft, wenn eine EUR-Transaktion gegen einen Fremdwährungs-Beleg gematcht wird:
# der Kartenanbieter rechnet um, deshalb sind die Zahlenwerte nie gleich.
# Die Bandbreiten sind bewusst großzügig - sie sollen Kursschwankungen abdecken, aber
# größenordnungsmäßige Fehlzuordnungen (Faktor 2 und mehr) ausschließen.
WECHSELKURS_BANDBREITEN = {
    'USD': (0.70, 1.10),
    'GBP': (1.00, 1.35),
    'CHF': (0.85, 1.20),
    'CAD': (0.55, 0.80),
    'AUD': (0.50, 0.75),
    'DKK': (0.11, 0.16),
    'SEK': (0.07, 0.12),
    'NOK': (0.07, 0.12),
    'PLN': (0.18, 0.28),
    'CZK': (0.03, 0.05),
    'JPY': (0.004, 0.010),
}

# Für nicht hinterlegte Währungen: nur grobe Ausreißer ausschließen, damit
# eine unbekannte Währung nicht pauschal jedes Matching blockiert.
WECHSELKURS_STANDARD_BANDBREITE = (0.05, 5.0)


def ist_kurs_plausibel(eur_betrag, fremdwaehrungs_betrag, waehrung):
    """Prüft, ob der implizite Umrechnungskurs für die Währung realistisch ist.

    Ohne diese Prüfung ist der Betrag bei Währungsdifferenz wertlos für das
    Matching, und bei wiederkehrenden Händlern (gleicher Name, gleiches Datum)
    entscheidet dann der Zufall - genau so entstehen Fehlzuordnungen.
    """
    if not eur_betrag or not fremdwaehrungs_betrag:
        return None

    kurs = eur_betrag / fremdwaehrungs_betrag
    unten, oben = WECHSELKURS_BANDBREITEN.get(
        (waehrung or '').upper(), WECHSELKURS_STANDARD_BANDBREITE
    )
    return unten <= kurs <= oben


def normalize_haendler(name):
    """Normalisiert einen Händlernamen für Vergleiche."""
    if not name:
        return ""

    name = name.lower().strip()

    # Entferne häufige Suffixe
    suffixes = [
        'gmbh', 'ag', 'kg', 'ohg', 'e.k.', 'ug', 'mbh', 'co.',
        'inc', 'ltd', 'llc', 'corp', 'sa', 'srl',
        'restaurant', 'hotel', 'gasthof', 'cafe', 'café'
    ]

    for suffix in suffixes:
        name = re.sub(rf'\b{suffix}\b\.?', '', name)

    # Entferne Sonderzeichen
    name = re.sub(r'[^\w\s]', ' ', name)

    # Mehrfache Leerzeichen entfernen
    name = ' '.join(name.split())

    return name.strip()


def parse_datum(datum_str):
    """Parst verschiedene Datumsformate."""
    if not datum_str:
        return None

    if isinstance(datum_str, datetime):
        return datum_str

    formats = [
        '%Y-%m-%d',
        '%d.%m.%Y',
        '%d.%m.%y',
        '%d/%m/%Y',
    ]

    for fmt in formats:
        try:
            return datetime.strptime(datum_str.strip(), fmt)
        except ValueError:
            continue

    return None


def calculate_match_score(transaktion, beleg):
    """
    Berechnet einen Match-Score zwischen Transaktion und Beleg.

    Gewichtung (bei gleicher Währung):
    - Betrag: 50% (wichtigster Faktor)
    - Datum: 30%
    - Händler/OCR: 20%

    Bei Fremdwährungen (Transaktion in USD, Beleg in USD):
    - Betrag: 20% (weniger wichtig wegen Wechselkurs-Differenz)
    - Datum: 30%
    - Händler/OCR: 50% (wichtiger für Matching)

    Returns:
        tuple: (score, details_dict)
    """
    score = 0.0
    details = {
        'betrag_match': False,
        'betrag_diff': None,
        'datum_diff': None,
        'haendler_similarity': 0.0,
        'ocr_match': False,
        'waehrung_mismatch': False
    }

    # Prüfe Währungen
    t_waehrung = (transaktion.get('waehrung') or 'EUR').upper()
    b_waehrung = (beleg.get('waehrung') or 'EUR').upper()

    # transaktionen.waehrung bezeichnet die Einkaufswährung, belastet wird aber in EUR.
    # Ist betrag_eur gesetzt, ist der Vergleichsbetrag also EUR - unabhängig davon,
    # worin eingekauft wurde. Ohne betrag_eur bleibt es beim Betrag in Einkaufswährung.
    t_vergleichswaehrung = 'EUR' if transaktion.get('betrag_eur') is not None else t_waehrung

    # Fremdwährungs-Transaktion mit gleichem Währungs-Beleg
    # (z.B. Transaktion in USD, Beleg in USD)
    is_foreign_currency_match = (
        t_vergleichswaehrung != 'EUR' and t_vergleichswaehrung == b_waehrung
    )

    # Transaktion in EUR aber Beleg in Fremdwährung (oder umgekehrt)
    is_currency_mismatch = (t_vergleichswaehrung != b_waehrung)

    if is_currency_mismatch and t_vergleichswaehrung != 'EUR' and b_waehrung != 'EUR':
        # Beide Fremdwährungen aber unterschiedlich - kein Match möglich
        details['waehrung_mismatch'] = True
        return 0.0, details

    # --- Betrag-Match ---
    t_betrag = transaktion.get('betrag_eur') or transaktion.get('betrag', 0)
    b_betrag = beleg.get('betrag', 0)

    # Gewichtung basierend auf Währungssituation
    if is_foreign_currency_match:
        # Fremdwährung: Betrag weniger wichtig (max 0.2), Händler wichtiger
        betrag_weight = 0.2
        haendler_weight = 0.5
    elif is_currency_mismatch:
        # EUR-Transaktion vs Fremdwährungs-Beleg: der direkte Betragsvergleich
        # scheitert am Wechselkurs, aber der implizite Kurs muss plausibel sein.
        betrag_weight = 0.2
        haendler_weight = 0.5
        details['waehrung_mismatch'] = True

        transaktion_ist_eur = t_vergleichswaehrung == 'EUR'
        fremdwaehrung = b_waehrung if transaktion_ist_eur else t_vergleichswaehrung
        eur_betrag = t_betrag if transaktion_ist_eur else b_betrag
        fremd_betrag = b_betrag if transaktion_ist_eur else t_betrag
        plausibel = ist_kurs_plausibel(eur_betrag, fremd_betrag, fremdwaehrung)

        if plausibel is False:
            # Die Beträge können denselben Vorgang nicht abbilden.
            details['kurs_unplausibel'] = True
            return 0.0, details

        if plausibel is True:
            details['kurs_unplausibel'] = False
            details['betrag_match'] = True
            score += betrag_weight

        # Betrag ist hier abschließend bewertet - kein zweiter Durchlauf unten.
        betrag_weight = 0.0
    else:
        # Beide EUR: normales Matching
        betrag_weight = 0.5
        haendler_weight = 0.2

    if t_betrag and b_betrag and betrag_weight > 0:
        betrag_diff = abs(t_betrag - b_betrag)
        details['betrag_diff'] = betrag_diff

        if betrag_diff < 0.01:
            score += betrag_weight
            details['betrag_match'] = True
        elif betrag_diff < 0.10:
            score += betrag_weight * 0.9
            details['betrag_match'] = True
        elif betrag_diff < 1.0:
            score += betrag_weight * 0.6
        elif betrag_diff < 5.0:
            score += betrag_weight * 0.2

    # --- Datum-Match (max 0.3) ---
    t_datum = parse_datum(transaktion.get('datum'))
    b_datum = parse_datum(beleg.get('datum'))

    if t_datum and b_datum:
        tage_diff = abs((t_datum - b_datum).days)
        details['datum_diff'] = tage_diff

        if tage_diff == 0:
            score += 0.3
        elif tage_diff <= 1:
            score += 0.25
        elif tage_diff <= 3:
            score += 0.2
        elif tage_diff <= 7:
            score += 0.1
        elif tage_diff <= 14:
            score += 0.05
        # Mehr als 14 Tage Differenz gibt keine Punkte

    # --- Händler-Match (max haendler_weight, default 0.2, higher for foreign currency) ---
    t_haendler = normalize_haendler(
        transaktion.get('haendler') or transaktion.get('beschreibung', '')
    )
    b_haendler = normalize_haendler(beleg.get('haendler', ''))

    haendler_score = 0.0

    if t_haendler and b_haendler:
        # Fuzzy String Matching
        similarity = SequenceMatcher(None, t_haendler, b_haendler).ratio()
        details['haendler_similarity'] = similarity

        if similarity > 0.9:
            haendler_score = haendler_weight
        elif similarity > 0.7:
            haendler_score = haendler_weight * 0.75
        elif similarity > 0.5:
            haendler_score = haendler_weight * 0.5
        elif similarity > 0.3:
            haendler_score = haendler_weight * 0.25

        # Bonus für exakte Wort-Übereinstimmung
        t_words = set(t_haendler.split())
        b_words = set(b_haendler.split())
        common_words = t_words & b_words

        if common_words and len(common_words) >= 1:
            word_bonus = min(0.05 * len(common_words), haendler_weight * 0.5)
            haendler_score += word_bonus

    # --- OCR-Text Match (alternative to haendler match) ---
    ocr_text = beleg.get('ocr_text', '')
    if ocr_text and t_haendler:
        ocr_normalized = ocr_text.lower()
        t_beschreibung = (transaktion.get('beschreibung') or '').lower()

        # Suche Transaktionsbeschreibung im OCR-Text
        ocr_score = 0.0

        # Extrahiere wichtige Wörter aus der Beschreibung (mind. 3 Zeichen)
        t_words = [w for w in t_beschreibung.split() if len(w) >= 3]

        if t_words:
            words_found = sum(1 for w in t_words if w in ocr_normalized)
            match_ratio = words_found / len(t_words)

            if match_ratio >= 0.8:
                ocr_score = haendler_weight
                details['ocr_match'] = True
            elif match_ratio >= 0.6:
                ocr_score = haendler_weight * 0.75
                details['ocr_match'] = True
            elif match_ratio >= 0.4:
                ocr_score = haendler_weight * 0.5
            elif match_ratio >= 0.2:
                ocr_score = haendler_weight * 0.25

        # Suche auch nach dem Betrag im OCR-Text (als Bestätigung)
        if t_betrag:
            betrag_str = f"{t_betrag:.2f}".replace('.', ',')
            betrag_str_dot = f"{t_betrag:.2f}"
            if betrag_str in ocr_text or betrag_str_dot in ocr_text:
                ocr_score = min(ocr_score + 0.1, 0.2)
                details['ocr_match'] = True

        # Nimm den besseren Score: Händler oder OCR
        score += max(haendler_score, ocr_score)
    else:
        score += haendler_score

    return min(score, 1.0), details


def find_matches(transaktion, belege, threshold=0.5):
    """
    Findet passende Belege für eine Transaktion.

    Args:
        transaktion: dict mit Transaktionsdaten
        belege: Liste von Beleg-dicts
        threshold: Minimum Score für einen Match

    Returns:
        Liste von Matches, sortiert nach Score (absteigend)
    """
    matches = []

    for beleg in belege:
        score, details = calculate_match_score(transaktion, beleg)

        if score >= threshold:
            matches.append({
                'beleg': beleg,
                'confidence': score,
                'match_details': details
            })

    return sorted(matches, key=lambda x: x['confidence'], reverse=True)


def auto_match_all(transaktionen, belege, threshold=0.7):
    """
    Führt automatisches Matching für alle Transaktionen durch.

    Args:
        transaktionen: Liste von Transaktionen
        belege: Liste von Belegen
        threshold: Höherer Threshold für Auto-Match

    Returns:
        dict mit Ergebnissen:
        {
            'matched': [(transaktion_id, beleg_id, confidence), ...],
            'multiple': [(transaktion_id, [beleg_ids...]), ...],
            'unmatched_transaktionen': [transaktion_ids...],
            'unmatched_belege': [beleg_ids...]
        }
    """
    result = {
        'matched': [],
        'multiple': [],
        'unmatched_transaktionen': [],
        'unmatched_belege': set(b.get('id') for b in belege)
    }

    for transaktion in transaktionen:
        t_id = transaktion.get('id')
        matches = find_matches(transaktion, belege, threshold)

        if not matches:
            result['unmatched_transaktionen'].append(t_id)
        elif len(matches) == 1:
            # Eindeutiger Match
            beleg_id = matches[0]['beleg'].get('id')
            result['matched'].append((t_id, beleg_id, matches[0]['confidence']))
            result['unmatched_belege'].discard(beleg_id)
        else:
            # Mehrere mögliche Matches
            beleg_ids = [m['beleg'].get('id') for m in matches[:5]]  # Top 5
            result['multiple'].append((t_id, beleg_ids))

    result['unmatched_belege'] = list(result['unmatched_belege'])

    return result


def suggest_matches(transaktion, belege, limit=5):
    """
    Schlägt die besten Matches für eine Transaktion vor.

    Returns:
        Liste der Top-Matches mit Details
    """
    matches = find_matches(transaktion, belege, threshold=0.3)
    return matches[:limit]
