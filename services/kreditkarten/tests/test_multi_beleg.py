"""Tests für Buchungen mit mehreren Belegen.

Händler schicken zur selben Belastung oft zwei Dokumente (Rechnung und
Zahlungsbestätigung). Beide hängen dann an derselben Buchung. Summen und Listen
müssen die Buchung trotzdem genau einmal zählen - ein LEFT JOIN auf belege
vervielfacht sonst die Buchungszeile.
"""

import io
import json
import os
import zipfile

import pytest


@pytest.fixture
def abrechnung_mit_mehrfachbelegen(app, sample_abrechnung):
    """Drei Buchungen: eine mit zwei Belegen, eine mit einem, eine ohne."""
    import app as app_module

    conn = app_module.get_db()

    def buchung(position, haendler, betrag, status):
        conn.execute('''
            INSERT INTO transaktionen
                (abrechnung_id, position, datum, haendler, beschreibung,
                 betrag, betrag_eur, waehrung, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'EUR', ?)
        ''', (sample_abrechnung, position, f'2026-01-0{position}', haendler,
              haendler.upper(), betrag, betrag, status))
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    def beleg(transaktion_id, datei_name, betrag):
        pfad = os.path.join(app_module.BELEGE_DIR, 'inbox', datei_name)
        with open(pfad, 'wb') as datei:
            datei.write(b'%PDF-1.4 Testbeleg')
        conn.execute('''
            INSERT INTO belege
                (transaktion_id, datei_name, datei_pfad, file_hash, extrahierte_daten)
            VALUES (?, ?, ?, ?, ?)
        ''', (transaktion_id, datei_name, pfad, f'hash-{datei_name}',
              json.dumps({'betrag': betrag, 'waehrung': 'EUR'})))

    zwei_belege = buchung(1, 'Anthropic', 100.00, 'zugeordnet')
    ein_beleg = buchung(2, 'Miro', 50.00, 'zugeordnet')
    ohne_beleg = buchung(3, 'Digital Charging', 25.00, 'offen')

    beleg(zwei_belege, 'Anthropic_Invoice.pdf', 100.00)
    beleg(zwei_belege, 'Anthropic_Receipt.pdf', 100.00)
    beleg(ein_beleg, 'Miro_Invoice.pdf', 50.00)

    conn.commit()
    conn.close()

    return {
        'abrechnung_id': sample_abrechnung,
        'zwei_belege': zwei_belege,
        'ein_beleg': ein_beleg,
        'ohne_beleg': ohne_beleg,
    }


class TestAbrechnungStatistik:
    """Die Statistik einer Abrechnung darf Buchungen nicht doppelt zählen."""

    def test_summe_zaehlt_buchung_mit_zwei_belegen_einmal(
            self, client, abrechnung_mit_mehrfachbelegen):
        response = client.get(
            f"/api/abrechnungen/{abrechnung_mit_mehrfachbelegen['abrechnung_id']}")
        assert response.status_code == 200

        statistik = json.loads(response.data)['statistik']
        assert statistik['summe'] == pytest.approx(175.00)

    def test_anzahl_entspricht_buchungen_nicht_belegen(
            self, client, abrechnung_mit_mehrfachbelegen):
        response = client.get(
            f"/api/abrechnungen/{abrechnung_mit_mehrfachbelegen['abrechnung_id']}")

        statistik = json.loads(response.data)['statistik']
        assert statistik['total'] == 3
        assert statistik['zugeordnet'] == 2
        assert statistik['offen'] == 1
        assert statistik['ignoriert'] == 0


class TestTransaktionenListe:
    """Die Transaktionsliste liefert pro Buchung genau eine Zeile."""

    def test_buchung_erscheint_nur_einmal(
            self, client, abrechnung_mit_mehrfachbelegen):
        response = client.get(
            f"/api/transaktionen?abrechnung_id={abrechnung_mit_mehrfachbelegen['abrechnung_id']}")
        assert response.status_code == 200

        zeilen = json.loads(response.data)
        assert len(zeilen) == 3
        assert len({zeile['id'] for zeile in zeilen}) == 3

    def test_anzahl_der_belege_wird_mitgeliefert(
            self, client, abrechnung_mit_mehrfachbelegen):
        response = client.get(
            f"/api/transaktionen?abrechnung_id={abrechnung_mit_mehrfachbelegen['abrechnung_id']}")
        zeilen = {zeile['id']: zeile for zeile in json.loads(response.data)}

        mehrfach = zeilen[abrechnung_mit_mehrfachbelegen['zwei_belege']]
        assert mehrfach['beleg_anzahl'] == 2
        assert mehrfach['beleg_id'] is not None
        assert mehrfach['beleg_datei'] in ('Anthropic_Invoice.pdf', 'Anthropic_Receipt.pdf')

        einfach = zeilen[abrechnung_mit_mehrfachbelegen['ein_beleg']]
        assert einfach['beleg_anzahl'] == 1
        assert einfach['beleg_datei'] == 'Miro_Invoice.pdf'

        ohne = zeilen[abrechnung_mit_mehrfachbelegen['ohne_beleg']]
        assert ohne['beleg_anzahl'] == 0
        assert ohne['beleg_id'] is None


class TestExportZip:
    """Das Export-ZIP muss alle Belege enthalten, auch den zweiten je Buchung."""

    def test_zip_enthaelt_beide_belege_einer_buchung(
            self, client, abrechnung_mit_mehrfachbelegen):
        response = client.get(
            f"/api/abrechnungen/{abrechnung_mit_mehrfachbelegen['abrechnung_id']}/export-zip")
        assert response.status_code == 200

        with zipfile.ZipFile(io.BytesIO(response.data)) as archiv:
            belege = [os.path.basename(name) for name in archiv.namelist()
                      if '/Belege/' in name]

        assert sorted(belege) == [
            'Anthropic_Invoice.pdf', 'Anthropic_Receipt.pdf', 'Miro_Invoice.pdf']


class TestBelegSpalte:
    """Die Belegspalte der Reports zeigt mehrere Belege als Zähler."""

    def test_ein_beleg_bleibt_unveraendert(self):
        from app import beleg_spalte
        assert beleg_spalte('Miro_Invoice.pdf', 1) == 'Miro_Invoice.pdf'

    def test_ohne_beleg_strich(self):
        from app import beleg_spalte
        assert beleg_spalte(None, 0) == '-'

    def test_mehrere_belege_mit_zaehler(self):
        from app import beleg_spalte
        assert beleg_spalte('Anthropic_Invoice.pdf', 2) == 'Anthropic_Invoice.pdf (+1)'

    def test_langer_name_wird_gekuerzt(self):
        from app import beleg_spalte
        name = 'A' * 80 + '.pdf'
        gekuerzt = beleg_spalte(name, 1)
        assert len(gekuerzt) == 60
        assert gekuerzt.endswith('...')
