"""Tests für Eigenbeleg-Feature."""

import json
import os
import pytest


class TestEigenbelegMigration:
    """Tests für die DB-Migration."""

    def test_belege_tabelle_hat_begruendung_spalte(self, app):
        """Migration fügt begruendung-Spalte zur belege-Tabelle hinzu."""
        import app as app_module
        conn = app_module.get_db()
        cols = [c[1] for c in conn.execute("PRAGMA table_info(belege)").fetchall()]
        conn.close()
        assert 'begruendung' in cols
