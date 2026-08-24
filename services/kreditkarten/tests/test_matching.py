"""
Tests für den Matching-Algorithmus.

Schwerpunkt: Plausibilitätsprüfung des impliziten Wechselkurses, wenn eine
EUR-Buchung gegen einen Beleg in Fremdwährung gematcht wird.
"""

from matching import calculate_match_score


def transaktion(betrag, waehrung='EUR', datum='2026-08-14', haendler='Cloud-Anbieter',
                betrag_eur=-1):
    """Minimale Transaktion, wie sie der Matcher aus der DB bekommt.

    `betrag_eur` ist in der Datenbank immer der belastete EUR-Betrag, während
    `waehrung` die Einkaufswährung bezeichnet. Default: identisch mit `betrag`,
    wie es der Import anlegt. `betrag_eur=None` simuliert Altbestand ohne das Feld.
    """
    return {
        'betrag': betrag,
        'betrag_eur': betrag if betrag_eur == -1 else betrag_eur,
        'waehrung': waehrung,
        'datum': datum,
        'haendler': haendler,
        'beschreibung': '',
    }


def beleg(betrag, waehrung='USD', datum='14.08.2026', haendler='Cloud-Anbieter Inc.'):
    """Minimaler Beleg, wie ihn die KI-Extraktion liefert."""
    return {
        'betrag': betrag,
        'waehrung': waehrung,
        'datum': datum,
        'haendler': haendler,
        'ocr_text': '',
    }


class TestWechselkursPlausibilitaet:
    """Der Betrag darf bei Währungsdifferenz nicht einfach ignoriert werden."""

    def test_betragsplausible_transaktion_schlaegt_unplausible(self):
        """900 USD entsprechen 800 € (Kurs 0,89), nicht 160 € (Kurs 0,18).

        Ohne Betragsbewertung sind beide Kandidaten gleichwertig, sobald sie
        denselben Händler und dasselbe Datum haben - dann entscheidet der Zufall.
        """
        rechnung = beleg(900.00)

        score_plausibel, _ = calculate_match_score(transaktion(800.00), rechnung)
        score_unplausibel, _ = calculate_match_score(transaktion(160.00), rechnung)

        assert score_plausibel > score_unplausibel

    def test_unplausibler_kurs_ergibt_keinen_treffer(self):
        """Ein Kurs von 0,18 USD/EUR ist unmöglich - die Belege gehören nicht zusammen."""
        score, details = calculate_match_score(transaktion(160.00), beleg(900.00))

        assert score == 0.0
        assert details.get('kurs_unplausibel') is True

    def test_plausibler_kurs_zaehlt_als_betragstreffer(self):
        _, details = calculate_match_score(transaktion(800.00), beleg(900.00))

        assert details['betrag_match'] is True
        assert details.get('kurs_unplausibel') is False

    def test_daenische_krone_nutzt_eigene_bandbreite(self):
        """1.000 DKK zu 137 € ergibt 0,137 - für DKK plausibel, für USD nicht."""
        taxi = beleg(1000.00, waehrung='DKK', datum='06.11.2025', haendler='Taxi Kopenhagen')
        tx = transaktion(137.00, datum='2025-11-06', haendler='Taxi Kopenhagen')

        _, details = calculate_match_score(tx, taxi)

        assert details['betrag_match'] is True
        assert details.get('kurs_unplausibel') is False

    def test_gleicher_zahlenwert_in_fremdwaehrung_ist_unplausibel(self):
        """500 CAD können nicht 500 € sein - typischer Extraktionsfehler."""
        score, details = calculate_match_score(
            transaktion(500.00, datum='2026-07-26', haendler='Hotelportal'),
            beleg(500.00, waehrung='CAD', datum='26.07.2026', haendler='Hotelportal'),
        )

        assert score == 0.0
        assert details.get('kurs_unplausibel') is True

    def test_unbekannte_waehrung_schliesst_nur_grobe_ausreisser_aus(self):
        """Ohne hinterlegte Bandbreite gilt ein weiter Rahmen, damit nichts blockiert wird."""
        _, plausibel = calculate_match_score(
            transaktion(88.00), beleg(100.00, waehrung='XYZ')
        )
        _, ausreisser = calculate_match_score(
            transaktion(1.00), beleg(100.00, waehrung='XYZ')
        )

        assert plausibel['betrag_match'] is True
        assert ausreisser.get('kurs_unplausibel') is True


class TestEinkaufswaehrungVersusBelasteterBetrag:
    """`waehrung` benennt die Einkaufswährung - belastet wird trotzdem in EUR.

    Ohne diese Unterscheidung behandelt der Matcher eine als USD markierte Buchung
    so, als stünde ihr Betrag in USD, und vergleicht EUR gegen USD.
    """

    def test_usd_buchung_mit_eur_betrag_wird_gegen_beleg_umgerechnet(self):
        """800 € belastet für eine 900-USD-Rechnung: Kurs 0,89, plausibel."""
        buchung = transaktion(800.00, waehrung='USD')

        _, details = calculate_match_score(buchung, beleg(900.00))

        assert details['betrag_match'] is True
        assert details.get('kurs_unplausibel') is False

    def test_falsche_buchung_wird_trotz_usd_kennzeichen_abgelehnt(self):
        """Eine 450-USD-Rechnung passt nicht zu einer 800-€-Buchung (Kurs 1,78)."""
        buchung = transaktion(800.00, waehrung='USD')

        score, details = calculate_match_score(buchung, beleg(450.00, datum='01.07.2026'))

        assert score == 0.0
        assert details.get('kurs_unplausibel') is True

    def test_eur_betrag_erlaubt_vergleich_mit_abweichender_fremdwaehrung(self):
        """Ist der belastete Betrag EUR, ist auch ein Beleg in dritter Währung vergleichbar."""
        buchung = transaktion(89.20, waehrung='CAD', haendler='Hostinganbieter')

        _, details = calculate_match_score(
            beleg=beleg(100.00, waehrung='USD', haendler='Hostinganbieter'),
            transaktion=buchung,
        )

        assert details['betrag_match'] is True

    def test_ohne_betrag_eur_bleibt_es_beim_direkten_fremdwaehrungsvergleich(self):
        """Altbestand ohne `betrag_eur`: Betrag und Beleg stehen in derselben Währung."""
        buchung = transaktion(100.00, waehrung='USD', betrag_eur=None,
                              haendler='Hostinganbieter')

        _, details = calculate_match_score(
            buchung, beleg(100.00, waehrung='USD', haendler='Hostinganbieter')
        )

        assert details['betrag_match'] is True
        assert details.get('kurs_unplausibel') is None


class TestBestehendesVerhalten:
    """Regressionsschutz: gleiche Währung und harte Ausschlüsse bleiben unverändert."""

    def test_exakter_eur_treffer_wird_weiter_hoch_gewichtet(self):
        score, details = calculate_match_score(
            transaktion(120.00, haendler='Ladestromanbieter'),
            beleg(120.00, waehrung='EUR', haendler='Ladestromanbieter GmbH'),
        )

        assert details['betrag_match'] is True
        assert score >= 0.5

    def test_zwei_verschiedene_fremdwaehrungen_matchen_nicht(self):
        """Ohne EUR-Betrag stehen beide Seiten in Fremdwährung - nicht vergleichbar."""
        score, details = calculate_match_score(
            transaktion(100.00, waehrung='USD', betrag_eur=None),
            beleg(100.00, waehrung='CAD'),
        )

        assert score == 0.0
        assert details['waehrung_mismatch'] is True

    def test_fehlender_belegbetrag_fuehrt_nicht_zum_absturz(self):
        score, details = calculate_match_score(transaktion(50.00), beleg(None))

        assert score >= 0.0
        assert details['betrag_match'] is False
