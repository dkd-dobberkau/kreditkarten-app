"""Tests für Eigenbeleg-Feature."""


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
