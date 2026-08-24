"""
Tests für die Benennung von Belegdateien bei der Zuordnung.

Belege werden nach Rechnungsdatum benannt, damit der Inbox- und Archivordner
chronologisch sortiert. Früher trug der Name die Positionsnummer der Buchung -
die ist innerhalb einer Abrechnung sinnvoll, sortiert über mehrere Monate hinweg
aber nach nichts.
"""

from app import beleg_dateiname


class TestBelegDateiname:

    def test_datum_wird_vorangestellt(self):
        assert beleg_dateiname('Rechnung-2026-0042.pdf', '14.08.2026') == \
            '2026-08-14_Rechnung-2026-0042.pdf'

    def test_positionspraefix_wird_durch_datum_ersetzt(self):
        assert beleg_dateiname('35_Rechnung-2026-0042.pdf', '14.08.2026') == \
            '2026-08-14_Rechnung-2026-0042.pdf'

    def test_vorhandenes_datum_wird_nicht_verdoppelt(self):
        """Wiederholtes Zuordnen darf den Namen nicht weiter aufblähen."""
        name = '2026-08-14_Cloud-Anbieter_Rechnung-2026-0043.pdf'

        assert beleg_dateiname(name, '14.08.2026') == name

    def test_iso_datum_wird_ebenfalls_verstanden(self):
        assert beleg_dateiname('Beleg.pdf', '2026-08-14') == '2026-08-14_Beleg.pdf'

    def test_ohne_datum_bleibt_der_name_ohne_praefix(self):
        """Kein Datum extrahiert: lieber gar kein Präfix als ein falsches."""
        assert beleg_dateiname('35_Invoice.pdf', None) == 'Invoice.pdf'

    def test_unlesbares_datum_wird_ignoriert(self):
        assert beleg_dateiname('12_Beleg.pdf', 'kein Datum') == 'Beleg.pdf'
