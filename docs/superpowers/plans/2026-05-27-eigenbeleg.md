# Eigenbeleg-Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eigenbeleg-Generierung pro Transaktion, damit eine Abrechnung trotz unbeschaffbarer Originalbelege auf `abgeschlossen` gehen kann.

**Architecture:** Additive DB-Spalte `belege.begruendung`, neuer Wert `'eigenbeleg'` für `belege.match_typ`, neuer Endpoint `POST /api/transaktionen/<id>/eigenbeleg` der ein ReportLab-PDF generiert und als gewöhnlichen Beleg verlinkt. UI im existierenden Transaktions-Detail-Modal.

**Tech Stack:** Flask, SQLite, ReportLab (bereits im Projekt), Materialize CSS, Vanilla JS, pytest.

**Spec:** `docs/superpowers/specs/2026-05-27-eigenbeleg-design.md`

---

## File Structure

**Modified files:**
- `services/kreditkarten/app.py` — DB-Migration in `init_db()`, PDF-Generator-Funktion `_generate_eigenbeleg_pdf()`, neuer Endpoint, erweiterte SELECT-Queries
- `services/kreditkarten/templates/index.html` — Modal-HTML-Block, neue JS-Funktionen, Eigenbeleg-Icon in der Transaktionsliste

**Created files:**
- `services/kreditkarten/tests/test_eigenbeleg.py` — Unit-Tests für PDF-Generator und Endpoint

Alle Änderungen bleiben innerhalb der bestehenden Datei-Boundaries. `app.py` ist mit ~2500 Zeilen schon groß; eine Refaktorierung in Module sprengt den Scope dieses Features.

---

## Task 1: DB-Migration — `begruendung`-Spalte

**Files:**
- Modify: `services/kreditkarten/app.py:299-417` (innerhalb `init_db()`)
- Test: `services/kreditkarten/tests/test_eigenbeleg.py` (neu)

Das Schema in `init_db()` verwendet nur `CREATE TABLE IF NOT EXISTS`, was keine neuen Spalten zu existierenden Tabellen hinzufügt. Wir ergänzen einen idempotenten `ALTER TABLE`-Block nach dem `executescript`.

- [ ] **Step 1.1: Test-Datei anlegen und Failing Test schreiben**

Datei `services/kreditkarten/tests/test_eigenbeleg.py`:

```python
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
```

- [ ] **Step 1.2: Test laufen lassen, FAIL erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegMigration -v"
```

Erwartet: FAIL mit "'begruendung' not in cols".

- [ ] **Step 1.3: Migration in `init_db()` einbauen**

In `services/kreditkarten/app.py` direkt nach `conn.executescript(...)` und vor `conn.commit()` (also vor Zeile 416), folgenden Block einfügen:

```python
    # Additive Migrationen (idempotent: ALTER TABLE läuft nur wenn Spalte fehlt)
    for migration in [
        "ALTER TABLE belege ADD COLUMN begruendung TEXT",
    ]:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError as e:
            if 'duplicate column name' not in str(e).lower():
                raise
```

- [ ] **Step 1.4: Test laufen lassen, PASS erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegMigration -v"
```

Erwartet: PASS.

- [ ] **Step 1.5: Auch gegen die echte Dev-DB migrieren**

```bash
ddev restart
ddev exec -s kreditkarten "python -c \"import sqlite3; con=sqlite3.connect('/app/data/kreditkarten.db'); print([c[1] for c in con.execute('PRAGMA table_info(belege)').fetchall()])\""
```

Erwartet: Output enthält `'begruendung'`.

- [ ] **Step 1.6: Commit**

```bash
git add services/kreditkarten/app.py services/kreditkarten/tests/test_eigenbeleg.py
git commit -m "Add belege.begruendung column for Eigenbeleg"
```

---

## Task 2: PDF-Generator-Funktion

**Files:**
- Modify: `services/kreditkarten/app.py` (neue Funktion direkt vor `create_bewirtungsbeleg`, ca. Zeile 2336)
- Test: `services/kreditkarten/tests/test_eigenbeleg.py`

Reine Funktion `_generate_eigenbeleg_pdf(transaktion, begruendung_text, einstellungen) -> bytes`. Pur (keine I/O), nimmt Dicts, gibt PDF-Bytes zurück. Damit unit-testbar.

- [ ] **Step 2.1: Failing Test schreiben**

In `services/kreditkarten/tests/test_eigenbeleg.py` anfügen:

```python
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
```

Falls `pdfminer` nicht installiert ist: in `services/kreditkarten/requirements.txt` (oder Equivalent) hinzufügen oder im Test über `try/except ImportError, pytest.skip(...)` schützen — prüfen mit:

```bash
ddev exec -s kreditkarten "pip show pdfminer.six 2>/dev/null || echo 'NOT INSTALLED'"
```

Falls nicht installiert: in `requirements.txt` `pdfminer.six` ergänzen und `ddev exec -s kreditkarten "pip install pdfminer.six"` einmal manuell.

- [ ] **Step 2.2: Test laufen lassen, FAIL erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegPdfGenerator -v"
```

Erwartet: FAIL mit "cannot import name '_generate_eigenbeleg_pdf' from 'app'".

- [ ] **Step 2.3: Funktion `_generate_eigenbeleg_pdf` implementieren**

In `services/kreditkarten/app.py`, direkt vor `@app.route('/api/transaktionen/<int:id>/bewirtungsbeleg', methods=['POST'])` (ca. Zeile 2336), neue Funktion einfügen:

```python
def _generate_eigenbeleg_pdf(transaktion: dict, begruendung_text: str, einstellungen: dict) -> bytes:
    """Erzeugt Eigenbeleg-PDF gemäß § 158 AO.

    Args:
        transaktion: Dict mit datum, haendler, beschreibung, betrag, waehrung, betrag_eur, kategorie.
        begruendung_text: Begründung warum kein Originalbeleg vorliegt.
        einstellungen: Dict mit name, firma, bewirtender_name, unterschrift_base64.

    Returns:
        PDF als Bytes.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO
    from datetime import datetime as dt
    import base64

    try:
        pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        font = 'DejaVu'
        font_bold = 'DejaVu-Bold'
    except Exception:
        font = 'Helvetica'
        font_bold = 'Helvetica-Bold'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=20*mm, bottomMargin=20*mm)

    title_style = ParagraphStyle('Title', fontName=font_bold, fontSize=18, spaceAfter=5,
                                 textColor=colors.HexColor('#333333'))
    subtitle_style = ParagraphStyle('Subtitle', fontName=font, fontSize=10,
                                    textColor=colors.grey, spaceAfter=15)
    label_style = ParagraphStyle('Label', fontName=font_bold, fontSize=10,
                                 textColor=colors.HexColor('#333333'))
    normal_style = ParagraphStyle('Normal', fontName=font, fontSize=10, leading=14)
    footer_style = ParagraphStyle('Footer', fontName=font, fontSize=8, textColor=colors.grey)

    elements = []

    elements.append(Paragraph("EIGENBELEG / ERSATZBELEG", title_style))
    elements.append(Paragraph("gemäß § 158 AO", subtitle_style))
    elements.append(Spacer(1, 5*mm))

    # Aussteller
    aussteller = einstellungen.get('firma') or einstellungen.get('name') or ''
    aussteller_name = einstellungen.get('name') or einstellungen.get('bewirtender_name') or ''
    elements.append(Paragraph("<b>Aussteller:</b>", label_style))
    elements.append(Paragraph(f"{aussteller_name}<br/>{aussteller}", normal_style))
    elements.append(Spacer(1, 8*mm))

    # Datum formatieren
    datum = transaktion.get('datum') or ''
    try:
        datum_formatted = dt.strptime(datum, '%Y-%m-%d').strftime('%d.%m.%Y')
    except (ValueError, TypeError):
        datum_formatted = datum

    betrag = transaktion.get('betrag_eur') or transaktion.get('betrag') or 0
    waehrung = transaktion.get('waehrung') or 'EUR'
    betrag_str = f"{betrag:,.2f} {waehrung}".replace(',', 'X').replace('.', ',').replace('X', '.')

    haendler = transaktion.get('haendler') or transaktion.get('beschreibung') or ''
    beschreibung = transaktion.get('beschreibung') or ''
    kategorie = transaktion.get('kategorie') or 'sonstiges'

    # Hauptdaten-Tabelle
    main_data = [
        [Paragraph("<b>Datum der Ausgabe:</b>", label_style), Paragraph(datum_formatted, normal_style)],
        [Paragraph("<b>Zahlungsempfänger:</b>", label_style), Paragraph(haendler, normal_style)],
        [Paragraph("<b>Beschreibung:</b>", label_style), Paragraph(beschreibung, normal_style)],
        [Paragraph("<b>Höhe der Ausgabe:</b>", label_style), Paragraph(betrag_str, normal_style)],
        [Paragraph("<b>Kategorie:</b>", label_style), Paragraph(kategorie, normal_style)],
    ]
    main_table = Table(main_data, colWidths=[55*mm, 115*mm])
    main_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
    ]))
    elements.append(main_table)
    elements.append(Spacer(1, 8*mm))

    # Begründung
    elements.append(Paragraph("<b>Begründung für Eigenbeleg:</b>", label_style))
    elements.append(Spacer(1, 2*mm))
    begr_table = Table([[Paragraph(begruendung_text, normal_style)]], colWidths=[170*mm])
    begr_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('MINROWHEIGHT', (0, 0), (-1, -1), 15*mm),
    ]))
    elements.append(begr_table)
    elements.append(Spacer(1, 10*mm))

    # Erstellungsdatum
    erstellt = dt.now().strftime('%d.%m.%Y')
    elements.append(Paragraph(f"<b>Datum der Belegerstellung:</b> {erstellt}", normal_style))
    elements.append(Spacer(1, 15*mm))

    # Unterschrift
    elements.append(Paragraph("<b>Unterschrift des Ausstellers:</b>", label_style))
    elements.append(Spacer(1, 3*mm))
    sig_b64 = einstellungen.get('unterschrift_base64')
    if sig_b64:
        try:
            sig_data = base64.b64decode(sig_b64.split(',')[1] if ',' in sig_b64 else sig_b64)
            sig_img = Image(BytesIO(sig_data), width=50*mm, height=15*mm)
            elements.append(sig_img)
        except Exception:
            elements.append(Spacer(1, 15*mm))
    else:
        elements.append(Spacer(1, 15*mm))

    sig_line = Table([['_' * 60]], colWidths=[170*mm])
    elements.append(sig_line)
    elements.append(Paragraph(f"Datum, Unterschrift: {aussteller_name}", normal_style))
    elements.append(Spacer(1, 10*mm))

    elements.append(Paragraph(
        "<i>Hinweis: Dieser Eigenbeleg dient als Ersatz für einen nicht beschaffbaren Originalbeleg "
        "gemäß § 158 AO.</i>",
        footer_style
    ))

    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data
```

- [ ] **Step 2.4: Test laufen lassen, PASS erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegPdfGenerator -v"
```

Erwartet: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add services/kreditkarten/app.py services/kreditkarten/tests/test_eigenbeleg.py
git commit -m "Add Eigenbeleg PDF generator function"
```

---

## Task 3: Backend-Endpoint — POST `/api/transaktionen/<id>/eigenbeleg`

**Files:**
- Modify: `services/kreditkarten/app.py` (neuer Endpoint direkt nach `_generate_eigenbeleg_pdf`)
- Test: `services/kreditkarten/tests/test_eigenbeleg.py`

- [ ] **Step 3.1: Failing Tests schreiben (Happy Path + Validation + Re-Submit)**

In `tests/test_eigenbeleg.py` anfügen:

```python
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
```

- [ ] **Step 3.2: Tests laufen lassen, alle FAIL erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegEndpoint -v"
```

Erwartet: FAIL (Endpoint existiert nicht, 404 für alle).

- [ ] **Step 3.3: Endpoint implementieren**

In `services/kreditkarten/app.py` direkt nach `_generate_eigenbeleg_pdf` einfügen:

```python
@app.route('/api/transaktionen/<int:id>/eigenbeleg', methods=['POST'])
def create_eigenbeleg(id):
    """Generiert Eigenbeleg-PDF und ordnet ihn der Transaktion zu."""
    import hashlib
    import os

    data = request.json or {}
    begruendung_text = (data.get('begruendung_text') or '').strip()
    if not begruendung_text:
        return jsonify({'error': 'Begründung darf nicht leer sein'}), 400

    conn = get_db()

    # Transaktion + Abrechnung + Konto laden
    transaktion = conn.execute('''
        SELECT t.*, a.periode, k.name as konto_name
        FROM transaktionen t
        JOIN abrechnungen a ON t.abrechnung_id = a.id
        JOIN konten k ON a.konto_id = k.id
        WHERE t.id = ?
    ''', (id,)).fetchone()
    if not transaktion:
        conn.close()
        return jsonify({'error': 'Transaktion nicht gefunden'}), 404

    # Existierenden Beleg prüfen
    bestehender_beleg = conn.execute(
        'SELECT * FROM belege WHERE transaktion_id = ?', (id,)
    ).fetchone()
    if bestehender_beleg and bestehender_beleg['match_typ'] != 'eigenbeleg':
        conn.close()
        return jsonify({'error': 'Transaktion hat bereits einen Originalbeleg'}), 400

    # Einstellungen (Aussteller-Daten)
    einstellungen_row = conn.execute('SELECT * FROM einstellungen WHERE id = 1').fetchone()
    einstellungen = dict(einstellungen_row) if einstellungen_row else {}

    # PDF generieren
    pdf_bytes = _generate_eigenbeleg_pdf(dict(transaktion), begruendung_text, einstellungen)

    # Speicherort bestimmen (verwendet bestehende Helper-Funktion)
    archiv_dir = get_archiv_path(transaktion['konto_name'], transaktion['periode'])
    filename = f"eigenbeleg_{id}.pdf"
    filepath = os.path.join(archiv_dir, filename)

    # PDF schreiben (überschreibt bei Re-Submit)
    with open(filepath, 'wb') as f:
        f.write(pdf_bytes)

    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # DB: Insert oder Update
    if bestehender_beleg:
        conn.execute('''
            UPDATE belege
            SET datei_name = ?, datei_pfad = ?, file_hash = ?,
                match_typ = ?, match_confidence = ?, begruendung = ?
            WHERE id = ?
        ''', (filename, filepath, file_hash, 'eigenbeleg', 1.0, begruendung_text,
              bestehender_beleg['id']))
        beleg_id = bestehender_beleg['id']
    else:
        cursor = conn.execute('''
            INSERT INTO belege (transaktion_id, datei_name, datei_pfad, file_hash,
                                match_typ, match_confidence, begruendung)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (id, filename, filepath, file_hash, 'eigenbeleg', 1.0, begruendung_text))
        beleg_id = cursor.lastrowid

    # Transaktion auf 'zugeordnet'
    conn.execute("UPDATE transaktionen SET status = 'zugeordnet' WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'beleg_id': beleg_id,
        'pdf_pfad': filepath,
    })
```

**Wichtig:** Der `INSERT`-Pfad kann am `file_hash UNIQUE`-Constraint scheitern, wenn das exakt selbe PDF schon einmal existierte. Da Datum und Begründungstext im PDF eingebettet sind, ist das in der Praxis fast unmöglich — das Erstellungsdatum macht jedes PDF unique. Falls es doch passiert, gibt SQLite einen `IntegrityError`. Belassen wir als bekannte Edge-Case, kein Workaround in v1.

- [ ] **Step 3.4: Tests laufen lassen, alle PASS erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestEigenbelegEndpoint -v"
```

Erwartet: alle 5 Tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add services/kreditkarten/app.py services/kreditkarten/tests/test_eigenbeleg.py
git commit -m "Add POST /api/transaktionen/<id>/eigenbeleg endpoint"
```

---

## Task 4: Transaktions-API um `beleg_match_typ` und `beleg_begruendung` erweitern

**Files:**
- Modify: `services/kreditkarten/app.py:1120-1145` (`get_transaktionen`)
- Test: `services/kreditkarten/tests/test_eigenbeleg.py`

Damit das Frontend Eigenbelege visuell unterscheiden kann, müssen die zwei Felder in den Transaktions-Responses mitgeliefert werden.

- [ ] **Step 4.1: Failing Test schreiben**

In `tests/test_eigenbeleg.py` anfügen:

```python
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
```

- [ ] **Step 4.2: Test laufen lassen, FAIL erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestTransaktionenApiEigenbelegFelder -v"
```

Erwartet: FAIL mit "KeyError: 'beleg_match_typ'".

- [ ] **Step 4.3: SELECT in `get_transaktionen` erweitern**

In `services/kreditkarten/app.py`, die zwei SELECT-Statements in `get_transaktionen` (ca. Zeile 1128 und 1136) modifizieren:

**Alt (Zeile ~1128):**
```python
            SELECT t.*, b.id as beleg_id, b.datei_name as beleg_datei
            FROM transaktionen t
            LEFT JOIN belege b ON t.id = b.transaktion_id
```

**Neu:**
```python
            SELECT t.*, b.id as beleg_id, b.datei_name as beleg_datei,
                   b.match_typ as beleg_match_typ, b.begruendung as beleg_begruendung
            FROM transaktionen t
            LEFT JOIN belege b ON t.id = b.transaktion_id
```

Gleich für das zweite SELECT (Zeile ~1136) ändern.

Außerdem in `loadAbrechnung` (Backend, ca. Zeile 860, falls dort auch ein SELECT mit belege-Join ist): nur ändern wenn `match_typ`/`begruendung` für das Frontend dort gebraucht werden — schauen ob `get_abrechnung()` die Transaktionen mitliefert.

```bash
grep -n "LEFT JOIN belege" services/kreditkarten/app.py
```

Für jeden Treffer prüfen: Liefert er Daten an das Frontend? Wenn ja, `match_typ` und `begruendung` ergänzen. Wenn nur intern (z.B. fürs Archivieren): unverändert lassen.

Konkret die relevanten Stellen aus der Recherche:
- Zeile ~860 (in einer GET-Abrechnung-Route): erweitern
- Zeile ~1128, ~1136 (in `get_transaktionen`): erweitern
- Zeile ~1998 (in Export-Route): unverändert lassen (Export braucht's nicht)
- Zeile ~2151 (in ZIP-Export): unverändert lassen

- [ ] **Step 4.4: Test laufen lassen, PASS erwarten**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/test_eigenbeleg.py::TestTransaktionenApiEigenbelegFelder -v"
```

Erwartet: PASS.

- [ ] **Step 4.5: Voll-Test-Lauf um keine Regression zu verursachen**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/ -v"
```

Erwartet: alle Tests PASS.

- [ ] **Step 4.6: Commit**

```bash
git add services/kreditkarten/app.py services/kreditkarten/tests/test_eigenbeleg.py
git commit -m "Expose match_typ and begruendung in transactions API"
```

---

## Task 5: Frontend — Modal-HTML für Eigenbeleg-Sektion

**Files:**
- Modify: `services/kreditkarten/templates/index.html` (`#transaktion-modal`-Block ab Zeile 651)

Im existierenden Transaktions-Detail-Modal nach dem `<div id="manual-assignment">`-Block (vor dem schließenden `</div>` von `.modal-content`, ca. Zeile 716) eine neue Sektion einfügen.

- [ ] **Step 5.1: HTML-Sektion einfügen**

Direkt vor `</div><!-- end modal-content -->` (Zeile ~717), folgenden Block einfügen:

```html
            <!-- Eigenbeleg-Erstellung (sichtbar wenn kein Beleg verlinkt) -->
            <div id="eigenbeleg-section" style="display: none; margin-top: 20px; border-top: 1px solid #ddd; padding-top: 16px;">
                <h5>Kein Originalbeleg vorhanden?</h5>
                <p class="grey-text">Erstellt einen Eigenbeleg gemäß § 158 AO als Ersatz für einen nicht beschaffbaren Originalbeleg.</p>

                <div id="eigenbeleg-form" style="display: none; margin-top: 12px;">
                    <p><strong>Begründung wählen:</strong></p>
                    <p>
                        <label>
                            <input name="eigenbeleg-grund" type="radio" value="Beleg nicht erhalten" checked />
                            <span>Beleg nicht erhalten</span>
                        </label>
                    </p>
                    <p>
                        <label>
                            <input name="eigenbeleg-grund" type="radio" value="Beleg verloren" />
                            <span>Beleg verloren</span>
                        </label>
                    </p>
                    <p>
                        <label>
                            <input name="eigenbeleg-grund" type="radio" value="Kein Beleg ausgestellt" />
                            <span>Kein Beleg ausgestellt</span>
                        </label>
                    </p>
                    <p>
                        <label>
                            <input name="eigenbeleg-grund" type="radio" value="__sonstiges__" id="eigenbeleg-grund-sonstiges" />
                            <span>Sonstiges</span>
                        </label>
                    </p>
                    <div class="input-field" id="eigenbeleg-sonstiges-field" style="display: none;">
                        <input type="text" id="eigenbeleg-sonstiges-text" />
                        <label for="eigenbeleg-sonstiges-text">Begründung (freier Text)</label>
                    </div>
                    <div style="margin-top: 12px;">
                        <a class="btn waves-effect waves-light" onclick="submitEigenbeleg()">
                            <i class="material-icons left">description</i>Eigenbeleg erstellen
                        </a>
                        <a class="btn-flat waves-effect" onclick="cancelEigenbelegForm()">Abbrechen</a>
                    </div>
                </div>

                <div id="eigenbeleg-trigger">
                    <a class="btn waves-effect waves-light orange" onclick="showEigenbelegForm()">
                        <i class="material-icons left">description</i>Eigenbeleg erstellen
                    </a>
                </div>
            </div>
```

- [ ] **Step 5.2: Manuell prüfen**

```bash
ddev restart
```

Im Browser `http://kreditkarten.ddev.site` öffnen, eine offene Transaktion anklicken: Der Block "Kein Originalbeleg vorhanden?" sollte am Ende des Modals erscheinen (auch wenn die Anzeige-Logik noch nicht greift — erstmal nur HTML-Struktur).

Hinweis: weil `display: none` gesetzt ist, ist der Block initial unsichtbar. Zum manuellen Prüfen vorübergehend `style="display: none"` entfernen oder per DevTools sichtbar machen. Danach wieder verstecken.

- [ ] **Step 5.3: Commit**

```bash
git add services/kreditkarten/templates/index.html
git commit -m "Add Eigenbeleg form HTML to transaction modal"
```

---

## Task 6: Frontend — JS-Logik für Eigenbeleg-Workflow

**Files:**
- Modify: `services/kreditkarten/templates/index.html` (JS-Block ab Zeile ~1069)

- [ ] **Step 6.1: Sichtbarkeit der Eigenbeleg-Sektion in `openTransaktion()` ergänzen**

In der Funktion `openTransaktion(id)` (ca. Zeile 1962), nach dem Setzen aller Detail-Felder, folgenden Block hinzufügen. Suche nach `M.FormSelect.init` in dieser Funktion und füge davor ein:

```javascript
            // Eigenbeleg-Sektion: nur sichtbar wenn Transaktion offen und kein Beleg verlinkt
            const eigenbelegSection = document.getElementById('eigenbeleg-section');
            const hatBeleg = t.beleg_id || t.beleg_datei;
            const istEigenbeleg = t.beleg_match_typ === 'eigenbeleg';
            if (t.status === 'offen' && !hatBeleg) {
                eigenbelegSection.style.display = 'block';
                document.getElementById('eigenbeleg-trigger').style.display = 'block';
                document.getElementById('eigenbeleg-form').style.display = 'none';
                document.getElementById('eigenbeleg-sonstiges-field').style.display = 'none';
                document.getElementById('eigenbeleg-sonstiges-text').value = '';
            } else if (istEigenbeleg) {
                // Hinweis dass es schon ein Eigenbeleg ist — Section bleibt versteckt
                eigenbelegSection.style.display = 'none';
            } else {
                eigenbelegSection.style.display = 'none';
            }
```

`t` ist hier das Transaktions-Objekt aus der API-Response (in der Funktion bereits vorhanden — falls die Variable anders heißt, anpassen; in `openTransaktion` heißt sie typischerweise `t` oder `data`).

**Verifizieren vor dem Einfügen:** Schau dir die Funktion an:

```bash
sed -n '1962,2020p' services/kreditkarten/templates/index.html
```

Nimm den Variablennamen für die geladenen Transaktions-Daten.

- [ ] **Step 6.2: Neue JS-Funktionen am Ende des `<script>`-Blocks anfügen**

Direkt vor dem schließenden `</script>` (Suche mit `grep -n "</script>" services/kreditkarten/templates/index.html | tail -1`):

```javascript
        // Eigenbeleg: Formular zeigen
        function showEigenbelegForm() {
            document.getElementById('eigenbeleg-trigger').style.display = 'none';
            document.getElementById('eigenbeleg-form').style.display = 'block';
        }

        // Eigenbeleg: Formular abbrechen
        function cancelEigenbelegForm() {
            document.getElementById('eigenbeleg-form').style.display = 'none';
            document.getElementById('eigenbeleg-trigger').style.display = 'block';
            document.getElementById('eigenbeleg-sonstiges-field').style.display = 'none';
            document.getElementById('eigenbeleg-sonstiges-text').value = '';
        }

        // Eigenbeleg: Sonstiges-Toggle
        document.addEventListener('change', function(e) {
            if (e.target.name === 'eigenbeleg-grund') {
                const sonstigesField = document.getElementById('eigenbeleg-sonstiges-field');
                if (e.target.value === '__sonstiges__') {
                    sonstigesField.style.display = 'block';
                } else {
                    sonstigesField.style.display = 'none';
                }
            }
        });

        // Eigenbeleg: Submit
        async function submitEigenbeleg() {
            if (!currentTransaktionId) return;
            const selected = document.querySelector('input[name="eigenbeleg-grund"]:checked');
            if (!selected) {
                M.toast({html: 'Bitte Begründung auswählen', classes: 'red'});
                return;
            }
            let begruendung_typ, begruendung_text;
            if (selected.value === '__sonstiges__') {
                begruendung_typ = 'sonstiges';
                begruendung_text = document.getElementById('eigenbeleg-sonstiges-text').value.trim();
                if (!begruendung_text) {
                    M.toast({html: 'Bitte Begründungstext eingeben', classes: 'red'});
                    return;
                }
            } else {
                // Mappe Label auf Typ
                const typMap = {
                    'Beleg nicht erhalten': 'beleg_nicht_erhalten',
                    'Beleg verloren': 'beleg_verloren',
                    'Kein Beleg ausgestellt': 'kein_beleg',
                };
                begruendung_typ = typMap[selected.value] || 'sonstiges';
                begruendung_text = selected.value;
            }

            try {
                const response = await fetch(`/api/transaktionen/${currentTransaktionId}/eigenbeleg`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ begruendung_typ, begruendung_text })
                });
                const data = await response.json();
                if (!response.ok) {
                    M.toast({html: data.error || 'Fehler beim Erstellen', classes: 'red'});
                    return;
                }
                M.toast({html: 'Eigenbeleg erstellt', classes: 'green'});
                M.Modal.getInstance(document.getElementById('transaktion-modal')).close();
                // Liste neu laden
                const abrechnungId = document.getElementById('abrechnung-select').value;
                if (abrechnungId) {
                    loadTransaktionen(abrechnungId);
                    loadAbrechnungBelege();
                }
            } catch (err) {
                M.toast({html: 'Netzwerkfehler', classes: 'red'});
                console.error(err);
            }
        }
```

- [ ] **Step 6.3: Manueller End-to-End-Test im Browser**

```bash
ddev restart
```

Browser → `http://kreditkarten.ddev.site`:
1. April-Abrechnung wählen.
2. Transaktion 226 (Google Cloud, 0,27 €) anklicken → Modal öffnet.
3. Unten erscheint orange Button "Eigenbeleg erstellen" → klicken.
4. Radio "Beleg nicht erhalten" ist vorausgewählt → "Eigenbeleg erstellen" klicken.
5. Toast "Eigenbeleg erstellt", Modal schließt.
6. Transaktion ist jetzt `zugeordnet` (grünes Icon).
7. Im Belege-Archiv `/app/belege/archiv/American_Express_Business_Card/April_2026/eigenbeleg_226.pdf` muss existieren.

Verifikation:
```bash
ddev exec -s kreditkarten "ls -la /app/belege/archiv/American_Express_Business_Card/April_2026/eigenbeleg_226.pdf"
```

PDF kann via PDF-Viewer-Modal angeschaut werden (Klick auf den verlinkten Beleg).

- [ ] **Step 6.4: Commit**

```bash
git add services/kreditkarten/templates/index.html
git commit -m "Wire Eigenbeleg form to backend in transaction modal"
```

---

## Task 7: Visuelle Differenzierung in der Transaktionsliste

**Files:**
- Modify: `services/kreditkarten/templates/index.html` (`renderTransaktionen` ca. Zeile 1845)

Wenn ein Beleg vom Typ `eigenbeleg` ist, anstelle des `attachment`-Icons ein `description`-Icon mit Tooltip "Eigenbeleg" anzeigen.

- [ ] **Step 7.1: Render-Logik anpassen**

In `services/kreditkarten/templates/index.html`, in `renderTransaktionen()` ca. Zeile 1899:

**Alt:**
```javascript
                                ${t.beleg_datei ? '<i class="material-icons tiny">attachment</i>' : ''}
```

**Neu:**
```javascript
                                ${t.beleg_datei ? (t.beleg_match_typ === 'eigenbeleg' ? '<i class="material-icons tiny" title="Eigenbeleg">description</i>' : '<i class="material-icons tiny" title="Beleg zugeordnet">attachment</i>') : ''}
```

- [ ] **Step 7.2: Im Browser prüfen**

```bash
ddev restart
```

Browser → April-Abrechnung wählen. Die Google-Cloud-Zeile (Transaktion 226 nach Eigenbeleg-Erstellung) zeigt jetzt das `description`-Icon. Andere zugeordnete Transaktionen zeigen weiter `attachment`.

- [ ] **Step 7.3: Commit**

```bash
git add services/kreditkarten/templates/index.html
git commit -m "Distinguish Eigenbeleg from original receipt in transaction list"
```

---

## Task 8: Smoke-Test der April-Abrechnung

**Files:** keine Änderungen, nur Verifikation.

- [ ] **Step 8.1: Voll-Test-Suite**

```bash
ddev exec -s kreditkarten "cd /app && pytest tests/ -v"
```

Erwartet: alle Tests PASS, inkl. der neuen `test_eigenbeleg.py`.

- [ ] **Step 8.2: April-Abrechnung — Verhalten der Status-Logik prüfen**

Bevor Eigenbeleg erstellt wird: Abrechnung 9 ist `offen` (3 offene Transaktionen: 216 Europa-Park, 226 Google Cloud — plus ggf. weitere).

Nach Erstellung des Eigenbelegs für Transaktion 226 und Erledigung der anderen offenen Transaktionen:

```bash
ddev exec -s kreditkarten "python -c \"import sqlite3; con=sqlite3.connect('/app/data/kreditkarten.db'); print(list(con.execute('SELECT id, periode, status FROM abrechnungen WHERE id=9').fetchone()))\""
```

Status sollte automatisch von `offen` auf `abgeschlossen` springen, sobald alle Transaktionen `zugeordnet` oder `ignoriert` sind (existierende Logik, siehe CLAUDE.md "Statement Status Logic").

- [ ] **Step 8.3: ZIP-Export prüfen**

Im Browser auf "ZIP exportieren" für die April-Abrechnung. Heruntergeladenes ZIP entpacken — der Eigenbeleg-PDF muss enthalten sein.

- [ ] **Step 8.4: Final-Commit (nur falls neue Änderungen offen sind)**

Üblicherweise nichts mehr zu committen. Falls noch Notizen/Doku-Updates angefallen sind, dann jetzt.

---

## Self-Review

- **Spec-Abdeckung:**
  - Datenmodell-Änderung → Task 1 ✓
  - PDF mit Pflichtangaben → Task 2 ✓
  - Endpoint mit Validierung + Re-Submit → Task 3 ✓
  - Frontend-Section im Modal → Task 5, 6 ✓
  - Visuelle Differenzierung → Task 7 ✓
  - Excel-Export — explizit out-of-scope laut Spec, keine Task ✓
- **Placeholder-Scan:** keine TBD/TODO im Plan, alle Code-Blöcke konkret.
- **Type-Konsistenz:** `_generate_eigenbeleg_pdf(transaktion, begruendung_text, einstellungen)` identisch in Task 2 (Implementation) und Task 3 (Aufruf). `match_typ='eigenbeleg'`, `match_confidence=1.0`, `begruendung` als Spaltenname durchgängig.
