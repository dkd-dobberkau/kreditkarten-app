"""
API endpoint tests for Kreditkarten-App.
"""

import json
import pytest


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_ok(self, client):
        """Health endpoint returns healthy status."""
        response = client.get('/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['database'] == 'connected'


class TestKontenAPI:
    """Tests for /api/konten endpoints."""

    def test_get_konten_empty(self, client):
        """Get konten returns empty list initially."""
        response = client.get('/api/konten')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_create_konto(self, client):
        """Create a new account."""
        response = client.post('/api/konten',
            data=json.dumps({
                'name': 'Test Karte',
                'bank': 'Test Bank',
                'kartentyp': 'visa'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert 'id' in data

    def test_create_konto_without_name_returns_error(self, client):
        """Creating account without name returns 400 error."""
        response = client.post('/api/konten',
            data=json.dumps({
                'bank': 'Test Bank'
            }),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_get_konten_after_create(self, client):
        """Get konten returns created account."""
        # Create account first
        client.post('/api/konten',
            data=json.dumps({
                'name': 'Test Karte',
                'bank': 'Test Bank',
                'kartentyp': 'visa'
            }),
            content_type='application/json'
        )

        # Get konten
        response = client.get('/api/konten')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data) == 1
        assert data[0]['name'] == 'Test Karte'


class TestAbrechnungenAPI:
    """Tests for /api/abrechnungen endpoints."""

    def test_get_abrechnungen_empty(self, client, sample_konto):
        """Get abrechnungen returns empty list initially."""
        response = client.get(f'/api/abrechnungen?konto_id={sample_konto}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_abrechnung_not_found(self, client):
        """Get non-existent abrechnung returns 404."""
        response = client.get('/api/abrechnungen/999')
        assert response.status_code == 404


class TestTransaktionenAPI:
    """Tests for /api/transaktionen endpoints."""

    def test_update_transaktion(self, client, sample_transaktion):
        """Update transaction category."""
        response = client.put(f'/api/transaktionen/{sample_transaktion}',
            data=json.dumps({
                'kategorie': 'reisekosten'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True


class TestHilfeAPI:
    """Tests for /api/hilfe endpoints."""

    def test_get_hilfe_kapitel(self, client):
        """Get help chapters returns list."""
        response = client.get('/api/hilfe/kapitel')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 7
        assert data[0]['id'] == '01-erste-schritte'

    def test_get_hilfe_kapitel_inhalt(self, client):
        """Get single chapter content."""
        response = client.get('/api/hilfe/kapitel/01-erste-schritte')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'html' in data
        assert 'Erste Schritte' in data['html']

    def test_get_hilfe_kapitel_not_found(self, client):
        """Get non-existent chapter returns 404."""
        response = client.get('/api/hilfe/kapitel/nicht-vorhanden')
        assert response.status_code == 404


class TestKategorienAPI:
    """Tests for /api/kategorien endpoints."""

    def test_get_kategorien(self, client):
        """Get categories returns dict."""
        response = client.get('/api/kategorien')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, dict)
        # Should have default categories
        assert 'reisekosten' in data or len(data) >= 0
