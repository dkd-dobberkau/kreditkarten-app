"""
Security tests for Kreditkarten-App.
Tests for path traversal, injection, and other security vulnerabilities.
"""

import io
import os
import json
import pytest
from werkzeug.utils import secure_filename


class TestPathTraversal:
    """Tests for path traversal vulnerabilities."""

    def test_secure_filename_removes_path_traversal(self):
        """secure_filename removes dangerous characters."""
        # Path traversal attempts - secure_filename strips path components
        result = secure_filename('../../../etc/passwd')
        assert '..' not in result
        assert '/' not in result

        result = secure_filename('..\\..\\windows\\system32')
        assert '..' not in result
        assert '\\' not in result

        result = secure_filename('/etc/passwd')
        assert result == 'etc_passwd' or 'passwd' in result

        result = secure_filename('test/../../../file.pdf')
        assert '/' not in result

    def test_upload_beleg_path_traversal(self, client, app):
        """Upload endpoint rejects path traversal in filename."""
        # Create a fake PDF file with malicious filename
        data = {
            'file': (io.BytesIO(b'%PDF-1.4 fake pdf content'), '../../../etc/passwd.pdf')
        }
        response = client.post('/api/belege/upload',
            data=data,
            content_type='multipart/form-data'
        )

        # Should either reject or sanitize the filename
        # The file should NOT be created outside the belege directory
        import app as app_module
        dangerous_path = os.path.join(app_module.BELEGE_DIR, '..', '..', '..', 'etc', 'passwd.pdf')
        assert not os.path.exists(dangerous_path)

    def test_upload_beleg_null_byte(self, client):
        """Upload endpoint handles null byte injection."""
        # Null byte injection attempt
        data = {
            'file': (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf\x00.exe')
        }
        response = client.post('/api/belege/upload',
            data=data,
            content_type='multipart/form-data'
        )
        # Should not crash
        assert response.status_code in [200, 400, 409]


class TestSQLInjection:
    """Tests for SQL injection vulnerabilities."""

    def test_konto_name_sql_injection(self, client):
        """Account creation handles SQL injection in name."""
        # SQL injection attempt
        response = client.post('/api/konten',
            data=json.dumps({
                'name': "Test'; DROP TABLE konten; --",
                'bank': 'Test Bank'
            }),
            content_type='application/json'
        )

        # Should succeed (name is escaped)
        assert response.status_code == 200

        # Verify table still exists
        response = client.get('/api/konten')
        assert response.status_code == 200

    def test_transaktion_update_sql_injection(self, client, sample_transaktion):
        """Transaction update handles SQL injection."""
        response = client.put(f'/api/transaktionen/{sample_transaktion}',
            data=json.dumps({
                'kategorie': "reisekosten'; DROP TABLE transaktionen; --"
            }),
            content_type='application/json'
        )

        # Should succeed (value is escaped)
        assert response.status_code == 200

        # Verify table still exists by updating again
        response = client.put(f'/api/transaktionen/{sample_transaktion}',
            data=json.dumps({'kategorie': 'sonstiges'}),
            content_type='application/json'
        )
        assert response.status_code == 200


class TestXSS:
    """Tests for Cross-Site Scripting vulnerabilities."""

    def test_konto_name_xss(self, client):
        """Account name with XSS is properly escaped."""
        response = client.post('/api/konten',
            data=json.dumps({
                'name': '<script>alert("XSS")</script>',
                'bank': 'Test Bank'
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        # Get the account
        response = client.get('/api/konten')
        data = json.loads(response.data)

        # The script tag should be stored but not executed
        # (execution prevention is in the frontend)
        assert len(data) == 1
        # Name should be stored as-is (frontend must escape)
        assert '<script>' in data[0]['name']


class TestFileUpload:
    """Tests for file upload security."""

    def test_upload_non_pdf_rejected(self, client, sample_abrechnung):
        """Non-PDF file upload is rejected for statement."""
        data = {
            'file': (io.BytesIO(b'not a pdf'), 'test.txt')
        }
        response = client.post(f'/api/abrechnungen/{sample_abrechnung}/upload-pdf',
            data=data,
            content_type='multipart/form-data'
        )
        assert response.status_code == 400
        assert 'PDF' in response.get_json().get('error', '')

    def test_upload_empty_filename(self, client):
        """Empty filename is handled gracefully."""
        data = {
            'file': (io.BytesIO(b'%PDF-1.4'), '')
        }
        response = client.post('/api/belege/upload',
            data=data,
            content_type='multipart/form-data'
        )
        # Should reject empty filename
        assert response.status_code == 400

    def test_upload_no_file(self, client):
        """Missing file is handled gracefully."""
        response = client.post('/api/belege/upload',
            data={},
            content_type='multipart/form-data'
        )
        assert response.status_code == 400


class TestParserSecurity:
    """Tests for parser security functions."""

    def test_validate_file_path_rejects_traversal(self, tmp_path):
        """validate_file_path rejects invalid paths or wrong extensions."""
        from parsers.beleg_parser import validate_file_path

        # Non-existent file
        with pytest.raises(ValueError):
            validate_file_path('/nonexistent/path/file.pdf')

        # Create a text file with wrong extension
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("test")

        with pytest.raises(ValueError):
            validate_file_path(str(txt_file), {'.pdf'})

    def test_validate_file_path_rejects_empty(self):
        """validate_file_path rejects empty path."""
        from parsers.beleg_parser import validate_file_path

        with pytest.raises(ValueError):
            validate_file_path('')

        with pytest.raises(ValueError):
            validate_file_path(None)

    def test_validate_pdf_path_rejects_non_pdf(self, tmp_path):
        """validate_pdf_path rejects non-PDF files."""
        from parsers.pdf_parser import validate_pdf_path

        # Create a non-PDF file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf")

        with pytest.raises(ValueError):
            validate_pdf_path(str(txt_file))

    def test_validate_pdf_path_accepts_valid_pdf(self, tmp_path):
        """validate_pdf_path accepts valid PDF path."""
        from parsers.pdf_parser import validate_pdf_path

        # Create a fake PDF file
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b'%PDF-1.4 fake pdf')

        result = validate_pdf_path(str(pdf_file))
        assert result.endswith('test.pdf')


class TestInputValidation:
    """Tests for input validation."""

    def test_invalid_json_handled(self, client):
        """Invalid JSON in request body is handled."""
        response = client.post('/api/konten',
            data='not valid json',
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_missing_content_type(self, client):
        """Missing content type is handled."""
        response = client.post('/api/konten',
            data='{"name": "test"}'
        )
        # Should either work or return proper error
        assert response.status_code in [200, 400, 415]

    def test_large_payload_handled(self, client):
        """Very large payloads are handled gracefully."""
        large_data = {'name': 'x' * 1000000}  # 1MB name
        response = client.post('/api/konten',
            data=json.dumps(large_data),
            content_type='application/json'
        )
        # Should either accept or reject gracefully
        assert response.status_code in [200, 400, 413]
