"""
pytest configuration and fixtures for Kreditkarten-App tests.
"""

import os
import sys
import tempfile
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app as flask_app, init_db, get_db


@pytest.fixture
def app():
    """Create application for testing."""
    # Use temporary directory for test data
    with tempfile.TemporaryDirectory() as tmpdir:
        flask_app.config.update({
            'TESTING': True,
            'DATA_DIR': tmpdir,
            'DATABASE': os.path.join(tmpdir, 'test.db'),
        })

        # Override global variables
        import app as app_module
        app_module.DATA_DIR = tmpdir
        app_module.DATABASE = os.path.join(tmpdir, 'test.db')
        app_module.BELEGE_DIR = os.path.join(tmpdir, 'belege')
        app_module.IMPORTS_DIR = os.path.join(tmpdir, 'imports')
        app_module.EXPORTS_DIR = os.path.join(tmpdir, 'exports')

        # Create directories
        os.makedirs(os.path.join(tmpdir, 'belege', 'inbox'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'belege', 'archiv'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'imports', 'inbox'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'imports', 'archiv'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'exports'), exist_ok=True)

        # Initialize database
        init_db()

        yield flask_app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create test CLI runner."""
    return app.test_cli_runner()


@pytest.fixture
def sample_konto(app):
    """Create a sample account for testing."""
    import app as app_module
    conn = app_module.get_db()
    conn.execute('''
        INSERT INTO konten (name, bank)
        VALUES (?, ?)
    ''', ('Test Kreditkarte', 'Test Bank'))
    conn.commit()
    konto_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return konto_id


@pytest.fixture
def sample_abrechnung(app, sample_konto):
    """Create a sample statement for testing."""
    import app as app_module
    conn = app_module.get_db()
    conn.execute('''
        INSERT INTO abrechnungen (konto_id, periode, status)
        VALUES (?, ?, ?)
    ''', (sample_konto, 'Januar 2026', 'offen'))
    conn.commit()
    abrechnung_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return abrechnung_id


@pytest.fixture
def sample_transaktion(app, sample_abrechnung):
    """Create a sample transaction for testing."""
    import app as app_module
    conn = app_module.get_db()
    conn.execute('''
        INSERT INTO transaktionen (abrechnung_id, datum, haendler, beschreibung, betrag, kategorie, position)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (sample_abrechnung, '2026-01-15', 'Test Shop', 'Testeinkauf', 99.99, 'sonstiges', 1))
    conn.commit()
    transaktion_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return transaktion_id
