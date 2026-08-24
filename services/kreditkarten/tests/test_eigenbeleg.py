"""Tests für Eigenbeleg-Feature."""

import json
import os


class TestEigenbelegMigration:
    """Tests für die DB-Migration."""

    def test_belege_tabelle_hat_begruendung_spalte(self, app):
        """Migration fügt begruendung-Spalte zur belege-Tabelle hinzu."""
        import app as app_module
        conn = app_module.get_db()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(belege)").fetchall()]
        conn.close()
        assert 'begruendung' in cols


class TestEigenbelegPdfGenerator:
    """Tests für die PDF-Generator-Funktion."""

    def test_pdf_enthaelt_pflichtfelder(self, app):
        """Das generierte PDF enthält alle Pflichtangaben."""
        from app import _generate_eigenbeleg_pdf

        transaktion = {
            'datum': '2026-04-01',
            'haendler': 'Google Cloud',
            'beschreibung': 'GOOGLE CLOUD EMEA LIMIT IRELAND',
            'betrag': 0.27,
            'waehrung': 'EUR',
            'betrag_eur': 0.27,
            'kategorie': 'software',
        }
        einstellungen = {
            'name': 'Olivier Dobberkau',
            'firma': 'dkd Internet Service GmbH',
            'bewirtender_name': 'Olivier Dobberkau',
            'unterschrift_base64': None,
        }
        pdf_bytes = _generate_eigenbeleg_pdf(transaktion, 'Beleg nicht erhalten', einstellungen)

        # PDF-Header
        assert pdf_bytes[:4] == b'%PDF'
        # Bytes extrahieren um auf Inhalt zu prüfen
        from pdfminer.high_level import extract_text
        from io import BytesIO
        text = extract_text(BytesIO(pdf_bytes))

        assert 'Eigenbeleg' in text or 'EIGENBELEG' in text
        assert '§ 158 AO' in text
        assert 'Google Cloud' in text
        assert '0,27' in text or '0.27' in text
        assert 'Beleg nicht erhalten' in text
        assert 'dkd Internet Service GmbH' in text
        assert 'Olivier Dobberkau' in text


class TestEigenbelegEndpoint:
    """Tests für POST /api/transaktionen/<id>/eigenbeleg."""

    def test_happy_path(self, client, sample_transaktion):
        """Endpoint erzeugt Eigenbeleg, ordnet ihn zu, setzt Transaktion auf zugeordnet."""
        import app as app_module
        response = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'beleg_nicht_erhalten',
                'begruendung_text': 'Beleg nicht erhalten',
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'beleg_id' in data
        assert 'pdf_pfad' in data

        # PDF existiert auf Platte
        assert os.path.exists(data['pdf_pfad'])

        # DB-Eintrag korrekt
        conn = app_module.get_db()
        beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (data['beleg_id'],)).fetchone()
        assert beleg['match_typ'] == 'eigenbeleg'
        assert beleg['match_confidence'] == 1.0
        assert beleg['begruendung'] == 'Beleg nicht erhalten'
        assert beleg['transaktion_id'] == sample_transaktion

        # Transaktions-Status
        t = conn.execute('SELECT status FROM transaktionen WHERE id = ?', (sample_transaktion,)).fetchone()
        assert t['status'] == 'zugeordnet'
        conn.close()

    def test_dateiname_traegt_das_buchungsdatum(self, client, sample_transaktion):
        """Wie jeder andere Beleg soll auch der Eigenbeleg chronologisch einsortieren."""
        response = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({'begruendung_text': 'Beleg nicht erhalten'}),
            content_type='application/json'
        )

        assert response.status_code == 200
        dateiname = os.path.basename(json.loads(response.data)['pdf_pfad'])
        assert dateiname == f'2026-01-15_eigenbeleg_{sample_transaktion}.pdf'

    def test_leere_begruendung_400(self, client, sample_transaktion):
        """Leerer Begründungs-Text → 400."""
        response = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'sonstiges',
                'begruendung_text': '   ',
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_nicht_existierende_transaktion_404(self, client, app):
        """Unbekannte Transaktion → 404."""
        response = client.post(
            '/api/transaktionen/99999/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'beleg_verloren',
                'begruendung_text': 'Beleg verloren',
            }),
            content_type='application/json'
        )
        assert response.status_code == 404

    def test_re_submit_aktualisiert(self, client, sample_transaktion):
        """Zweiter POST überschreibt PDF und aktualisiert DB-Eintrag."""
        import app as app_module
        # Erster POST
        r1 = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'beleg_verloren',
                'begruendung_text': 'Beleg verloren',
            }),
            content_type='application/json'
        )
        beleg_id_1 = json.loads(r1.data)['beleg_id']

        # Zweiter POST mit anderer Begründung
        r2 = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'sonstiges',
                'begruendung_text': 'Andere Begründung',
            }),
            content_type='application/json'
        )
        assert r2.status_code == 200
        beleg_id_2 = json.loads(r2.data)['beleg_id']

        # Gleiche beleg_id (Update, kein Insert)
        assert beleg_id_1 == beleg_id_2

        conn = app_module.get_db()
        beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (beleg_id_2,)).fetchone()
        assert beleg['begruendung'] == 'Andere Begründung'

        # Genau ein Beleg für die Transaktion
        count = conn.execute('SELECT COUNT(*) FROM belege WHERE transaktion_id = ?',
                             (sample_transaktion,)).fetchone()[0]
        assert count == 1
        conn.close()

    def test_originalbeleg_vorhanden_400(self, client, sample_transaktion):
        """Wenn schon ein Originalbeleg verlinkt ist → 400."""
        import app as app_module
        conn = app_module.get_db()
        conn.execute('''
            INSERT INTO belege (transaktion_id, datei_name, datei_pfad, file_hash, match_typ, match_confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (sample_transaktion, 'rechnung.pdf', '/tmp/rechnung.pdf', 'hash123', 'manuell', 1.0))
        conn.execute('UPDATE transaktionen SET status = ? WHERE id = ?', ('zugeordnet', sample_transaktion))
        conn.commit()
        conn.close()

        response = client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'beleg_verloren',
                'begruendung_text': 'Beleg verloren',
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'Originalbeleg' in data['error']


class TestTransaktionenApiEigenbelegFelder:
    """Tests dass die Transaktions-API match_typ und begruendung mitliefert."""

    def test_transaktionen_endpoint_liefert_match_typ_und_begruendung(self, client, sample_transaktion):
        """Nach Eigenbeleg-Erstellung enthält GET /api/transaktionen die neuen Felder."""
        # Eigenbeleg erstellen
        client.post(
            f'/api/transaktionen/{sample_transaktion}/eigenbeleg',
            data=json.dumps({
                'begruendung_typ': 'beleg_verloren',
                'begruendung_text': 'Beleg verloren',
            }),
            content_type='application/json'
        )

        # Get transaktionen
        import app as app_module
        conn = app_module.get_db()
        abrechnung_id = conn.execute(
            'SELECT abrechnung_id FROM transaktionen WHERE id = ?', (sample_transaktion,)
        ).fetchone()['abrechnung_id']
        conn.close()

        response = client.get(f'/api/transaktionen?abrechnung_id={abrechnung_id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        t = next(x for x in data if x['id'] == sample_transaktion)
        assert t['beleg_match_typ'] == 'eigenbeleg'
        assert t['beleg_begruendung'] == 'Beleg verloren'

    def test_transaktion_ohne_beleg_liefert_null_felder(self, client, sample_transaktion):
        """Transaktion ohne Beleg liefert beleg_match_typ=None und beleg_begruendung=None.

        Schützt gegen versehentliche Änderung des LEFT JOIN zu INNER JOIN.
        """
        import app as app_module
        conn = app_module.get_db()
        abrechnung_id = conn.execute(
            'SELECT abrechnung_id FROM transaktionen WHERE id = ?', (sample_transaktion,)
        ).fetchone()['abrechnung_id']
        conn.close()

        response = client.get(f'/api/transaktionen?abrechnung_id={abrechnung_id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        t = next(x for x in data if x['id'] == sample_transaktion)
        assert t['beleg_match_typ'] is None
        assert t['beleg_begruendung'] is None
