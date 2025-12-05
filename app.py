"""
Kreditkarten-Abgleich App - Flask Backend
"""

from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import anthropic
import sqlite3
import hashlib
import json
import os
import re
import io

load_dotenv()

app = Flask(__name__)

# Directories
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
EXPORTS_DIR = os.environ.get('EXPORTS_DIR', os.path.join(os.path.dirname(__file__), 'exports'))
BELEGE_DIR = os.path.join(os.path.dirname(__file__), 'belege')
IMPORTS_DIR = os.path.join(os.path.dirname(__file__), 'imports')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(os.path.join(BELEGE_DIR, 'inbox'), exist_ok=True)
os.makedirs(os.path.join(BELEGE_DIR, 'archiv'), exist_ok=True)
os.makedirs(os.path.join(IMPORTS_DIR, 'inbox'), exist_ok=True)
os.makedirs(os.path.join(IMPORTS_DIR, 'archiv'), exist_ok=True)

DATABASE = os.path.join(DATA_DIR, 'kreditkarten.db')
CACHE_FILE = os.path.join(DATA_DIR, '.cache.json')

# Deutsche Monatsnamen
MONAT_NAMEN = {
    1: 'Januar', 2: 'Februar', 3: 'März', 4: 'April',
    5: 'Mai', 6: 'Juni', 7: 'Juli', 8: 'August',
    9: 'September', 10: 'Oktober', 11: 'November', 12: 'Dezember'
}

MONAT_KURZ = {
    'jan': 1, 'feb': 2, 'mär': 3, 'mar': 3, 'apr': 4,
    'mai': 5, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'okt': 10, 'oct': 10, 'nov': 11, 'dez': 12, 'dec': 12
}

# Kategorien für Geschäftsausgaben
KATEGORIEN = {
    'bewirtung': 'Restaurants, Cafés, Bars',
    'reise_hotel': 'Hotels, Unterkünfte',
    'reise_flug': 'Flugtickets',
    'reise_bahn': 'Bahntickets',
    'reise_taxi': 'Taxi, Uber, Mietwagen',
    'buero': 'Bürobedarf, Schreibwaren',
    'software': 'Software, Abonnements, SaaS',
    'hardware': 'Computer, Geräte',
    'telefon': 'Telefon, Mobilfunk',
    'porto': 'Porto, Versand',
    'fachliteratur': 'Bücher, Zeitschriften',
    'fortbildung': 'Kurse, Konferenzen',
    'werbung': 'Marketing, Werbung',
    'versicherung': 'Versicherungen',
    'gebuehren': 'Bankgebühren, Kartengebühren',
    'privat': 'Private Ausgaben (nicht absetzbar)',
    'sonstiges': 'Sonstige Geschäftsausgaben'
}


# =============================================================================
# Database Functions
# =============================================================================

def get_db():
    """Get database connection with Row factory."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database with schema."""
    conn = get_db()
    conn.executescript('''
        -- Kreditkarten-Konten
        CREATE TABLE IF NOT EXISTS konten (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            inhaber TEXT,
            kartennummer_letzte4 TEXT,
            kartennummer_encrypted TEXT,
            bank TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Monatliche Abrechnungen
        CREATE TABLE IF NOT EXISTS abrechnungen (
            id INTEGER PRIMARY KEY,
            konto_id INTEGER REFERENCES konten(id),
            periode TEXT NOT NULL,
            abrechnungsdatum DATE,
            gesamtbetrag REAL,
            status TEXT DEFAULT 'offen',
            file_hash TEXT,
            datei_pfad TEXT,
            datei_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(konto_id, periode)
        );

        -- Einzelne Transaktionen
        CREATE TABLE IF NOT EXISTS transaktionen (
            id INTEGER PRIMARY KEY,
            abrechnung_id INTEGER REFERENCES abrechnungen(id),
            position INTEGER,
            datum DATE NOT NULL,
            buchungsdatum DATE,
            beschreibung TEXT,
            haendler TEXT,
            betrag REAL NOT NULL,
            waehrung TEXT DEFAULT 'EUR',
            betrag_eur REAL,
            kategorie TEXT,
            kategorie_confidence REAL,
            status TEXT DEFAULT 'offen',
            notizen TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Zugeordnete Belege
        CREATE TABLE IF NOT EXISTS belege (
            id INTEGER PRIMARY KEY,
            transaktion_id INTEGER REFERENCES transaktionen(id),
            datei_name TEXT,
            datei_pfad TEXT,
            file_hash TEXT UNIQUE,
            extrahierte_daten TEXT,
            match_confidence REAL,
            match_typ TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Kategorien mit Regeln
        CREATE TABLE IF NOT EXISTS kategorie_regeln (
            id INTEGER PRIMARY KEY,
            kategorie TEXT NOT NULL,
            muster TEXT NOT NULL,
            prioritaet INTEGER DEFAULT 0,
            aktiv BOOLEAN DEFAULT 1
        );

        -- Einstellungen
        CREATE TABLE IF NOT EXISTS einstellungen (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT,
            firma TEXT,
            standard_kategorie TEXT DEFAULT 'sonstiges',
            auto_kategorisieren BOOLEAN DEFAULT 1,
            auto_matching BOOLEAN DEFAULT 1
        );

        -- Default-Einstellungen
        INSERT OR IGNORE INTO einstellungen (id, standard_kategorie) VALUES (1, 'sonstiges');
    ''')
    conn.commit()
    conn.close()


# =============================================================================
# Encryption Functions
# =============================================================================

def get_cipher():
    """Get Fernet cipher for encryption."""
    key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        key_file = os.path.join(DATA_DIR, 'secret.key')
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
    return Fernet(key if isinstance(key, bytes) else key.encode())


def encrypt(data):
    """Encrypt sensitive data."""
    if not data:
        return None
    return get_cipher().encrypt(data.encode()).decode()


def decrypt(encrypted):
    """Decrypt sensitive data."""
    if not encrypted:
        return None
    return get_cipher().decrypt(encrypted.encode()).decode()


# =============================================================================
# Helper Functions
# =============================================================================

def parse_monat_string(monat_str):
    """Parse month string and return (year, month)."""
    if not monat_str:
        now = datetime.now()
        return now.year, now.month

    monat_str = monat_str.lower().strip()

    for kurz, num in MONAT_KURZ.items():
        if kurz in monat_str:
            year_match = re.search(r'(20\d{2})', monat_str)
            if year_match:
                return int(year_match.group(1)), num

    match = re.search(r'(\d{1,2})[/\-.]?(20\d{2})', monat_str)
    if match:
        return int(match.group(2)), int(match.group(1))

    now = datetime.now()
    return now.year, now.month


def get_file_hash(content):
    """Calculate MD5 hash of content."""
    if isinstance(content, str):
        content = content.encode()
    return hashlib.md5(content).hexdigest()


def load_cache():
    """Load processing cache."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache(cache):
    """Save processing cache."""
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# =============================================================================
# Claude AI Integration
# =============================================================================

def get_anthropic_client():
    """Get Anthropic API client."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def kategorisiere_transaktion(beschreibung, betrag, datum):
    """Categorize a transaction using Claude AI."""
    try:
        client = get_anthropic_client()

        kategorien_liste = "\n".join([f"- {k}: {v}" for k, v in KATEGORIEN.items()])

        prompt = f"""Analysiere diese Kreditkarten-Transaktion und kategorisiere sie.

Transaktion:
- Datum: {datum}
- Beschreibung: {beschreibung}
- Betrag: {betrag:.2f} EUR

Verfügbare Kategorien:
{kategorien_liste}

Antworte NUR mit JSON:
{{
    "haendler": "Normalisierter Händlername",
    "kategorie": "kategorie_key",
    "confidence": 0.0-1.0,
    "geschaeftlich": true/false,
    "notiz": "Optional: Kurze Erklärung"
}}"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0]

        return json.loads(response_text.strip())
    except Exception as e:
        return {
            "haendler": beschreibung[:50],
            "kategorie": "sonstiges",
            "confidence": 0.0,
            "geschaeftlich": True,
            "notiz": f"AI-Fehler: {str(e)}"
        }


def kategorisiere_batch(transaktionen):
    """Categorize multiple transactions in one API call."""
    if not transaktionen:
        return []

    try:
        client = get_anthropic_client()
        kategorien_liste = "\n".join([f"- {k}: {v}" for k, v in KATEGORIEN.items()])

        # Build transaction list for prompt
        trans_list = []
        for i, t in enumerate(transaktionen):
            trans_list.append(f"{i+1}. Datum: {t['datum']} | Beschreibung: {t['beschreibung']} | Betrag: {t['betrag']:.2f} EUR")

        prompt = f"""Analysiere diese Kreditkarten-Transaktionen und kategorisiere sie.

Transaktionen:
{chr(10).join(trans_list)}

Verfügbare Kategorien:
{kategorien_liste}

Antworte NUR mit einem JSON-Array. Für jede Transaktion (in der gleichen Reihenfolge):
[
    {{
        "haendler": "Normalisierter Händlername",
        "kategorie": "kategorie_key",
        "confidence": 0.0-1.0,
        "geschaeftlich": true/false,
        "notiz": "Kurze Erklärung"
    }},
    ...
]"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text
        if '```json' in response_text:
            response_text = response_text.split('```json')[1].split('```')[0]
        elif '```' in response_text:
            response_text = response_text.split('```')[1].split('```')[0]

        results = json.loads(response_text.strip())

        # Ensure we have the same number of results
        if len(results) != len(transaktionen):
            raise ValueError(f"Got {len(results)} results for {len(transaktionen)} transactions")

        return results

    except Exception as e:
        # Fallback: return default values for all
        return [{
            "haendler": t['beschreibung'][:50],
            "kategorie": "sonstiges",
            "confidence": 0.0,
            "geschaeftlich": True,
            "notiz": f"AI-Fehler: {str(e)}"
        } for t in transaktionen]


# =============================================================================
# API Routes
# =============================================================================

@app.route('/')
def index():
    """Serve main page."""
    return render_template('index.html')


@app.route('/health')
def health():
    """Health check endpoint."""
    try:
        conn = get_db()
        conn.execute('SELECT 1')
        conn.close()
        db_status = 'connected'
    except Exception:
        db_status = 'error'

    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': db_status
    })


# --- Konten ---

@app.route('/api/konten', methods=['GET'])
def get_konten():
    """Get all credit card accounts."""
    conn = get_db()
    konten = conn.execute('SELECT * FROM konten ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(k) for k in konten])


@app.route('/api/konten', methods=['POST'])
def create_konto():
    """Create a new credit card account."""
    data = request.json
    conn = get_db()

    kartennummer = None
    if data.get('kartennummer'):
        kartennummer = encrypt(data['kartennummer'])

    cursor = conn.execute(
        'INSERT INTO konten (name, inhaber, kartennummer_letzte4, kartennummer_encrypted, bank) VALUES (?, ?, ?, ?, ?)',
        (data['name'], data.get('inhaber'), data.get('kartennummer_letzte4'), kartennummer, data.get('bank'))
    )
    konto_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({'id': konto_id, 'success': True})


@app.route('/api/konten/<int:id>', methods=['PUT'])
def update_konto(id):
    """Update credit card account."""
    data = request.json
    conn = get_db()

    conn.execute(
        'UPDATE konten SET inhaber = ?, kartennummer_letzte4 = ? WHERE id = ?',
        (data.get('inhaber'), data.get('kartennummer_letzte4'), id)
    )
    conn.commit()
    conn.close()

    return jsonify({'success': True})


# --- Abrechnungen ---

@app.route('/api/abrechnungen', methods=['GET'])
def get_abrechnungen():
    """Get all statements, optionally filtered by account."""
    konto_id = request.args.get('konto_id')
    conn = get_db()

    if konto_id:
        abrechnungen = conn.execute('''
            SELECT a.*, k.name as konto_name
            FROM abrechnungen a
            LEFT JOIN konten k ON a.konto_id = k.id
            WHERE a.konto_id = ?
            ORDER BY a.periode DESC
        ''', (konto_id,)).fetchall()
    else:
        abrechnungen = conn.execute('''
            SELECT a.*, k.name as konto_name
            FROM abrechnungen a
            LEFT JOIN konten k ON a.konto_id = k.id
            ORDER BY a.periode DESC
        ''').fetchall()

    conn.close()
    return jsonify([dict(a) for a in abrechnungen])


@app.route('/api/abrechnungen/<int:id>', methods=['GET'])
def get_abrechnung(id):
    """Get statement details with statistics."""
    conn = get_db()

    abrechnung = conn.execute('''
        SELECT a.*, k.name as konto_name, k.inhaber, k.kartennummer_letzte4
        FROM abrechnungen a
        LEFT JOIN konten k ON a.konto_id = k.id
        WHERE a.id = ?
    ''', (id,)).fetchone()

    if not abrechnung:
        conn.close()
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    # Statistics - use actual beleg assignment, not status field
    stats = conn.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN b.id IS NOT NULL OR t.status = 'zugeordnet' THEN 1 ELSE 0 END) as zugeordnet,
            SUM(CASE WHEN b.id IS NULL AND t.status != 'ignoriert' THEN 1 ELSE 0 END) as offen,
            SUM(CASE WHEN t.status = 'ignoriert' THEN 1 ELSE 0 END) as ignoriert,
            SUM(t.betrag_eur) as summe
        FROM transaktionen t
        LEFT JOIN belege b ON t.id = b.transaktion_id
        WHERE t.abrechnung_id = ?
    ''', (id,)).fetchone()

    conn.close()

    result = dict(abrechnung)
    result['statistik'] = dict(stats) if stats else {}
    return jsonify(result)


@app.route('/api/abrechnungen/<int:id>/download')
def download_abrechnung(id):
    """Download the original statement PDF."""
    conn = get_db()
    abrechnung = conn.execute(
        'SELECT * FROM abrechnungen WHERE id = ?', (id,)
    ).fetchone()
    conn.close()

    if not abrechnung:
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    filepath = abrechnung['datei_pfad']
    if not filepath or not os.path.exists(filepath):
        return jsonify({'error': 'Datei nicht gefunden'}), 404

    return send_file(filepath, as_attachment=False)


@app.route('/api/abrechnungen/<int:id>/upload-pdf', methods=['POST'])
def upload_abrechnung_pdf(id):
    """Upload/attach a PDF to an existing statement."""
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Nur PDF-Dateien erlaubt'}), 400

    conn = get_db()
    abrechnung = conn.execute(
        'SELECT * FROM abrechnungen WHERE id = ?', (id,)
    ).fetchone()

    if not abrechnung:
        conn.close()
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    # Save PDF
    content = file.read()
    safe_filename = file.filename.replace('/', '_').replace('\\', '_')
    filepath = os.path.join(IMPORTS_DIR, 'archiv', safe_filename)

    counter = 1
    base, ext = os.path.splitext(safe_filename)
    while os.path.exists(filepath):
        safe_filename = f"{base}_{counter}{ext}"
        filepath = os.path.join(IMPORTS_DIR, 'archiv', safe_filename)
        counter += 1

    with open(filepath, 'wb') as f:
        f.write(content)

    # Update database
    conn.execute('''
        UPDATE abrechnungen SET datei_pfad = ?, datei_name = ? WHERE id = ?
    ''', (filepath, file.filename, id))
    conn.commit()
    conn.close()

    return jsonify({'success': True, 'filename': safe_filename})


@app.route('/api/abrechnungen/<int:id>', methods=['DELETE'])
def delete_abrechnung(id):
    """Delete a statement and all its transactions."""
    conn = get_db()

    # Get statement info
    abrechnung = conn.execute(
        'SELECT * FROM abrechnungen WHERE id = ?', (id,)
    ).fetchone()

    if not abrechnung:
        conn.close()
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    # Delete associated PDF file if exists
    if abrechnung['datei_pfad'] and os.path.exists(abrechnung['datei_pfad']):
        try:
            os.remove(abrechnung['datei_pfad'])
        except OSError:
            pass  # Ignore file deletion errors

    # Delete transactions first (foreign key)
    conn.execute('DELETE FROM transaktionen WHERE abrechnung_id = ?', (id,))

    # Delete statement
    conn.execute('DELETE FROM abrechnungen WHERE id = ?', (id,))

    conn.commit()
    conn.close()

    return jsonify({'success': True})


@app.route('/api/abrechnungen/import', methods=['POST'])
def import_abrechnung():
    """Import a credit card statement (CSV or PDF)."""
    from parsers import parse_csv, detect_bank_format, parse_amex_pdf

    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400

    file = request.files['file']
    konto_id = request.form.get('konto_id')
    periode = request.form.get('periode')

    if not konto_id:
        return jsonify({'error': 'Konto-ID erforderlich'}), 400

    content = file.read()
    file_hash = get_file_hash(content)
    filename = file.filename.lower()

    # Check for duplicate
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM abrechnungen WHERE file_hash = ?',
        (file_hash,)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'Diese Abrechnung wurde bereits importiert', 'id': existing['id']}), 409

    # Save file permanently
    saved_filepath = None
    original_filename = file.filename

    # Parse based on file type
    if filename.endswith('.pdf'):
        # Save PDF permanently
        safe_filename = original_filename.replace('/', '_').replace('\\', '_')
        saved_filepath = os.path.join(IMPORTS_DIR, 'archiv', safe_filename)

        # Handle duplicates
        counter = 1
        base, ext = os.path.splitext(safe_filename)
        while os.path.exists(saved_filepath):
            safe_filename = f"{base}_{counter}{ext}"
            saved_filepath = os.path.join(IMPORTS_DIR, 'archiv', safe_filename)
            counter += 1

        with open(saved_filepath, 'wb') as f:
            f.write(content)

        try:
            result = parse_amex_pdf(saved_filepath)
            transaktionen = result.get('transaktionen', [])
            if not periode and result.get('periode'):
                periode = result['periode']
        except Exception as e:
            # Keep the file but return error
            return jsonify({'error': f'PDF-Parsing fehlgeschlagen: {str(e)}'}), 400
    else:
        # Parse CSV
        try:
            content_str = content.decode('utf-8')
        except UnicodeDecodeError:
            content_str = content.decode('iso-8859-1')

        bank_format = detect_bank_format(content_str)
        transaktionen = parse_csv(content_str, bank_format)

    if not transaktionen:
        conn.close()
        return jsonify({'error': 'Keine Transaktionen gefunden'}), 400

    # Auto-detect period if not provided
    if not periode and transaktionen:
        first_date = transaktionen[0].get('datum')
        if first_date:
            try:
                dt = datetime.strptime(first_date, '%Y-%m-%d')
                periode = f"{MONAT_NAMEN[dt.month]} {dt.year}"
            except ValueError:
                periode = datetime.now().strftime('%B %Y')

    # Calculate totals
    gesamtbetrag = sum(t.get('betrag', 0) for t in transaktionen)
    gutschriften = sum(1 for t in transaktionen if t.get('betrag', 0) < 0)

    # Create statement
    cursor = conn.execute('''
        INSERT INTO abrechnungen (konto_id, periode, gesamtbetrag, file_hash, datei_pfad, datei_name, status)
        VALUES (?, ?, ?, ?, ?, ?, 'offen')
    ''', (konto_id, periode, gesamtbetrag, file_hash, saved_filepath, original_filename))
    abrechnung_id = cursor.lastrowid

    # Insert transactions with position number
    for idx, t in enumerate(transaktionen, start=1):
        conn.execute('''
            INSERT INTO transaktionen
            (abrechnung_id, position, datum, buchungsdatum, beschreibung, betrag, waehrung, betrag_eur, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'offen')
        ''', (
            abrechnung_id,
            idx,
            t.get('datum'),
            t.get('buchungsdatum'),
            t.get('beschreibung'),
            t.get('betrag'),
            t.get('waehrung', 'EUR'),
            t.get('betrag_eur', t.get('betrag'))
        ))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'id': abrechnung_id,
        'transaktionen': len(transaktionen),
        'gutschriften': gutschriften,
        'gesamtbetrag': gesamtbetrag
    })


# --- Transaktionen ---

@app.route('/api/transaktionen', methods=['GET'])
def get_transaktionen():
    """Get transactions, optionally filtered by statement."""
    abrechnung_id = request.args.get('abrechnung_id')
    conn = get_db()

    if abrechnung_id:
        transaktionen = conn.execute('''
            SELECT t.*, b.id as beleg_id, b.datei_name as beleg_datei
            FROM transaktionen t
            LEFT JOIN belege b ON t.id = b.transaktion_id
            WHERE t.abrechnung_id = ?
            ORDER BY t.position ASC
        ''', (abrechnung_id,)).fetchall()
    else:
        transaktionen = conn.execute('''
            SELECT t.*, b.id as beleg_id, b.datei_name as beleg_datei
            FROM transaktionen t
            LEFT JOIN belege b ON t.id = b.transaktion_id
            ORDER BY t.position ASC
            LIMIT 100
        ''').fetchall()

    conn.close()
    return jsonify([dict(t) for t in transaktionen])


@app.route('/api/transaktionen/<int:id>', methods=['PUT'])
def update_transaktion(id):
    """Update a transaction (category, status, notes)."""
    data = request.json
    conn = get_db()

    updates = []
    params = []

    for field in ['kategorie', 'status', 'notizen', 'haendler']:
        if field in data:
            updates.append(f'{field} = ?')
            params.append(data[field])

    if updates:
        params.append(id)
        conn.execute(
            f'UPDATE transaktionen SET {", ".join(updates)} WHERE id = ?',
            params
        )
        conn.commit()

    conn.close()
    return jsonify({'success': True})


@app.route('/api/transaktionen/<int:id>/kategorisieren', methods=['POST'])
def kategorisiere_transaktion_api(id):
    """Auto-categorize a transaction using AI."""
    conn = get_db()
    transaktion = conn.execute(
        'SELECT * FROM transaktionen WHERE id = ?', (id,)
    ).fetchone()

    if not transaktion:
        conn.close()
        return jsonify({'error': 'Transaktion nicht gefunden'}), 404

    result = kategorisiere_transaktion(
        transaktion['beschreibung'],
        transaktion['betrag_eur'] or transaktion['betrag'],
        transaktion['datum']
    )

    conn.execute('''
        UPDATE transaktionen
        SET haendler = ?, kategorie = ?, kategorie_confidence = ?, notizen = ?
        WHERE id = ?
    ''', (
        result.get('haendler'),
        result.get('kategorie'),
        result.get('confidence'),
        result.get('notiz'),
        id
    ))
    conn.commit()
    conn.close()

    return jsonify(result)


@app.route('/api/transaktionen/kategorisieren-alle', methods=['POST'])
def kategorisiere_alle():
    """Auto-categorize all uncategorized transactions in a statement using batch processing."""
    abrechnung_id = request.json.get('abrechnung_id')
    batch_size = 15  # Process 15 transactions per API call

    conn = get_db()
    transaktionen = conn.execute('''
        SELECT * FROM transaktionen
        WHERE abrechnung_id = ? AND (kategorie IS NULL OR kategorie = '')
        ORDER BY position
    ''', (abrechnung_id,)).fetchall()

    if not transaktionen:
        conn.close()
        return jsonify({'success': True, 'kategorisiert': 0, 'ergebnisse': []})

    results = []

    # Process in batches
    for i in range(0, len(transaktionen), batch_size):
        batch = transaktionen[i:i + batch_size]

        # Prepare batch data
        batch_data = [{
            'id': t['id'],
            'datum': t['datum'],
            'beschreibung': t['beschreibung'],
            'betrag': t['betrag_eur'] or t['betrag']
        } for t in batch]

        # Categorize batch
        batch_results = kategorisiere_batch(batch_data)

        # Update database and collect results
        for t, result in zip(batch, batch_results):
            conn.execute('''
                UPDATE transaktionen
                SET haendler = ?, kategorie = ?, kategorie_confidence = ?, notizen = ?
                WHERE id = ?
            ''', (
                result.get('haendler'),
                result.get('kategorie'),
                result.get('confidence'),
                result.get('notiz'),
                t['id']
            ))
            results.append({'id': t['id'], **result})

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'kategorisiert': len(results), 'ergebnisse': results})


# --- Belege ---

@app.route('/api/belege', methods=['GET'])
def get_belege():
    """Get all receipts, optionally unassigned only."""
    nur_unzugeordnet = request.args.get('unzugeordnet') == 'true'
    conn = get_db()

    if nur_unzugeordnet:
        belege = conn.execute('''
            SELECT * FROM belege WHERE transaktion_id IS NULL
            ORDER BY created_at DESC
        ''').fetchall()
    else:
        belege = conn.execute('''
            SELECT b.*, t.beschreibung as transaktion_beschreibung
            FROM belege b
            LEFT JOIN transaktionen t ON b.transaktion_id = t.id
            ORDER BY b.created_at DESC
        ''').fetchall()

    conn.close()
    return jsonify([dict(b) for b in belege])


@app.route('/api/belege/<int:id>/download')
def download_beleg(id):
    """Download a receipt file."""
    conn = get_db()
    beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (id,)).fetchone()
    conn.close()

    if not beleg:
        return jsonify({'error': 'Beleg nicht gefunden'}), 404

    filepath = beleg['datei_pfad']
    if not os.path.exists(filepath):
        return jsonify({'error': 'Datei nicht gefunden'}), 404

    return send_file(filepath, as_attachment=False)


@app.route('/api/belege/upload', methods=['POST'])
def upload_beleg():
    """Upload and process a receipt."""
    from parsers import extract_beleg_data

    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400

    file = request.files['file']
    content = file.read()
    file_hash = get_file_hash(content)

    # Check for duplicate
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM belege WHERE file_hash = ?', (file_hash,)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'error': 'Dieser Beleg existiert bereits', 'id': existing['id']}), 409

    # Save file
    filename = file.filename
    filepath = os.path.join(BELEGE_DIR, 'inbox', filename)

    counter = 1
    base, ext = os.path.splitext(filename)
    while os.path.exists(filepath):
        filename = f"{base}_{counter}{ext}"
        filepath = os.path.join(BELEGE_DIR, 'inbox', filename)
        counter += 1

    with open(filepath, 'wb') as f:
        f.write(content)

    # Extract data with AI
    extracted = extract_beleg_data(filepath)

    # Save to database
    cursor = conn.execute('''
        INSERT INTO belege (datei_name, datei_pfad, file_hash, extrahierte_daten)
        VALUES (?, ?, ?, ?)
    ''', (filename, filepath, file_hash, json.dumps(extracted)))
    beleg_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'id': beleg_id,
        'filename': filename,
        'extrahiert': extracted
    })


@app.route('/api/belege/scan-folder', methods=['POST'])
def scan_belege_folder():
    """Scan inbox folder for new receipts and process them."""
    from parsers import extract_beleg_data

    inbox_dir = os.path.join(BELEGE_DIR, 'inbox')
    if not os.path.exists(inbox_dir):
        return jsonify({'error': 'Inbox-Verzeichnis nicht gefunden'}), 404

    conn = get_db()

    # Get existing file hashes
    existing_hashes = set(
        row['file_hash'] for row in
        conn.execute('SELECT file_hash FROM belege WHERE file_hash IS NOT NULL').fetchall()
    )

    results = []
    errors = []

    for filename in os.listdir(inbox_dir):
        if filename.startswith('.'):
            continue

        filepath = os.path.join(inbox_dir, filename)
        if not os.path.isfile(filepath):
            continue

        # Check file type
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ['.pdf', '.png', '.jpg', '.jpeg']:
            continue

        # Get file hash
        with open(filepath, 'rb') as f:
            content = f.read()

        # Skip empty files
        if len(content) == 0:
            continue

        file_hash = get_file_hash(content)

        # Skip if already processed
        if file_hash in existing_hashes:
            continue

        try:
            # Extract data with AI
            extracted = extract_beleg_data(filepath)

            # Save to database
            cursor = conn.execute('''
                INSERT INTO belege (datei_name, datei_pfad, file_hash, extrahierte_daten)
                VALUES (?, ?, ?, ?)
            ''', (filename, filepath, file_hash, json.dumps(extracted)))
            beleg_id = cursor.lastrowid

            existing_hashes.add(file_hash)

            results.append({
                'id': beleg_id,
                'datei': filename,
                'extrahiert': extracted
            })
        except Exception as e:
            errors.append({
                'datei': filename,
                'error': str(e)
            })

    conn.commit()
    conn.close()

    return jsonify({
        'neue_belege': len(results),
        'fehler': len(errors),
        'details': results,
        'errors': errors
    })


@app.route('/api/belege/<int:id>/zuordnen', methods=['POST'])
def zuordne_beleg(id):
    """Assign or unassign a receipt to/from a transaction."""
    import re as regex

    transaktion_id = request.json.get('transaktion_id')
    match_typ = request.json.get('match_typ', 'manuell')
    confidence = request.json.get('confidence', 1.0 if match_typ == 'manuell' else 0.5)

    conn = get_db()

    # Get current beleg info
    beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (id,)).fetchone()
    if not beleg:
        conn.close()
        return jsonify({'error': 'Beleg nicht gefunden'}), 404

    # Get current assignment to update old transaction status
    old_transaktion_id = beleg['transaktion_id']

    new_filename = beleg['datei_name']
    new_filepath = beleg['datei_pfad']

    # Rename file with position prefix when assigning
    if transaktion_id:
        # Get transaction position
        transaktion = conn.execute(
            'SELECT position FROM transaktionen WHERE id = ?', (transaktion_id,)
        ).fetchone()

        if transaktion and transaktion['position']:
            position = transaktion['position']
            old_filename = beleg['datei_name']
            old_filepath = beleg['datei_pfad']

            # Remove existing prefix (e.g., "01_" or "99_")
            base_name = regex.sub(r'^\d{2}_', '', old_filename)

            # Add new prefix
            new_filename = f"{position:02d}_{base_name}"
            new_filepath = os.path.join(os.path.dirname(old_filepath), new_filename)

            # Rename file if it exists and name changed
            if old_filepath != new_filepath and os.path.exists(old_filepath):
                # Handle potential conflicts
                if os.path.exists(new_filepath):
                    base, ext = os.path.splitext(new_filename)
                    counter = 1
                    while os.path.exists(new_filepath):
                        new_filename = f"{base}_{counter}{ext}"
                        new_filepath = os.path.join(os.path.dirname(old_filepath), new_filename)
                        counter += 1

                os.rename(old_filepath, new_filepath)

    # Update receipt assignment and file info
    conn.execute('''
        UPDATE belege
        SET transaktion_id = ?, match_typ = ?, match_confidence = ?, datei_name = ?, datei_pfad = ?
        WHERE id = ?
    ''', (transaktion_id, match_typ, confidence, new_filename, new_filepath, id))

    # Update old transaction status if unassigning
    if old_transaktion_id:
        conn.execute('''
            UPDATE transaktionen SET status = 'offen' WHERE id = ?
        ''', (old_transaktion_id,))

    # Update new transaction status if assigning
    if transaktion_id:
        conn.execute('''
            UPDATE transaktionen SET status = 'zugeordnet' WHERE id = ?
        ''', (transaktion_id,))

    conn.commit()
    conn.close()

    return jsonify({'success': True, 'new_filename': new_filename})


@app.route('/api/belege/re-extract', methods=['POST'])
def re_extract_belege():
    """Re-extract data from receipts using AI."""
    from parsers import extract_beleg_data

    beleg_ids = request.json.get('beleg_ids', [])

    conn = get_db()

    # Get belege to re-extract
    if beleg_ids:
        placeholders = ','.join('?' * len(beleg_ids))
        belege = conn.execute(
            f'SELECT * FROM belege WHERE id IN ({placeholders})', beleg_ids
        ).fetchall()
    else:
        # Re-extract all belege without structured data
        belege = conn.execute('''
            SELECT * FROM belege WHERE extrahierte_daten IS NULL
            OR json_extract(extrahierte_daten, '$.betrag') IS NULL
        ''').fetchall()

    results = []
    for beleg in belege:
        filepath = beleg['datei_pfad']
        if not os.path.exists(filepath):
            results.append({'id': beleg['id'], 'error': 'Datei nicht gefunden'})
            continue

        # Re-extract with AI
        extracted = extract_beleg_data(filepath)

        # Update database
        conn.execute('''
            UPDATE belege SET extrahierte_daten = ? WHERE id = ?
        ''', (json.dumps(extracted), beleg['id']))

        results.append({
            'id': beleg['id'],
            'filename': beleg['datei_name'],
            'extracted': extracted
        })

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'processed': len(results),
        'results': results
    })


@app.route('/api/belege/auto-match', methods=['POST'])
def auto_match_belege():
    """Automatically match receipts to transactions."""
    from matching import calculate_match_score

    abrechnung_id = request.json.get('abrechnung_id')
    threshold = request.json.get('threshold', 0.5)

    conn = get_db()

    # Get unassigned receipts
    belege_rows = conn.execute('''
        SELECT * FROM belege WHERE transaktion_id IS NULL
    ''').fetchall()

    # Get open transactions
    if abrechnung_id:
        transaktionen_rows = conn.execute('''
            SELECT * FROM transaktionen
            WHERE abrechnung_id = ? AND status = 'offen'
        ''', (abrechnung_id,)).fetchall()
    else:
        transaktionen_rows = conn.execute('''
            SELECT * FROM transaktionen WHERE status = 'offen'
        ''').fetchall()

    # Prepare beleg data
    belege = []
    for b in belege_rows:
        try:
            extracted = json.loads(b['extrahierte_daten'] or '{}')
        except json.JSONDecodeError:
            extracted = {}

        belege.append({
            'id': b['id'],
            'datei_name': b['datei_name'],
            'betrag': extracted.get('betrag'),
            'datum': extracted.get('datum'),
            'haendler': extracted.get('haendler'),
            'waehrung': extracted.get('waehrung', 'EUR'),
            'ocr_text': extracted.get('ocr_text', '')
        })

    # Prepare transaction data
    transaktionen = [dict(t) for t in transaktionen_rows]

    matches_found = []
    matched_transaktion_ids = set()

    # For each beleg, find the best matching transaction
    for beleg in belege:
        best_match = None
        best_score = 0

        for t in transaktionen:
            # Skip already matched transactions
            if t['id'] in matched_transaktion_ids:
                continue

            # Calculate match score
            score, details = calculate_match_score(t, beleg)

            if score > best_score:
                best_score = score
                best_match = t

        # If good match found, create assignment
        if best_match and best_score >= threshold:
            # Get original beleg info for file rename
            beleg_row = conn.execute(
                'SELECT datei_name, datei_pfad FROM belege WHERE id = ?', (beleg['id'],)
            ).fetchone()

            old_filename = beleg_row['datei_name']
            old_filepath = beleg_row['datei_pfad']
            new_filename = old_filename
            new_filepath = old_filepath

            # Rename file with position prefix
            position = best_match.get('position')
            if position and old_filepath:
                import re as regex
                # Remove existing position prefix (e.g., "01_")
                base_name = regex.sub(r'^\d{2}_', '', old_filename)
                new_filename = f"{position:02d}_{base_name}"
                new_filepath = os.path.join(os.path.dirname(old_filepath), new_filename)

                # Rename file if it exists
                if old_filepath != new_filepath and os.path.exists(old_filepath):
                    if os.path.exists(new_filepath):
                        base, ext = os.path.splitext(new_filename)
                        counter = 1
                        while os.path.exists(new_filepath):
                            new_filename = f"{base}_{counter}{ext}"
                            new_filepath = os.path.join(os.path.dirname(old_filepath), new_filename)
                            counter += 1
                    os.rename(old_filepath, new_filepath)

            conn.execute('''
                UPDATE belege
                SET transaktion_id = ?, match_typ = 'auto', match_confidence = ?,
                    datei_name = ?, datei_pfad = ?
                WHERE id = ?
            ''', (best_match['id'], best_score, new_filename, new_filepath, beleg['id']))

            conn.execute('''
                UPDATE transaktionen SET status = 'zugeordnet' WHERE id = ?
            ''', (best_match['id'],))

            matched_transaktion_ids.add(best_match['id'])

            matches_found.append({
                'beleg_id': beleg['id'],
                'beleg_name': new_filename,
                'transaktion_id': best_match['id'],
                'transaktion_beschreibung': best_match['beschreibung'],
                'confidence': round(best_score, 2)
            })

            # Remove matched transaction from pool
            transaktionen = [t for t in transaktionen if t['id'] != best_match['id']]

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'matched': len(matches_found),
        'details': matches_found
    })


# --- Export ---

@app.route('/api/abrechnungen/<int:id>/export', methods=['GET'])
def export_abrechnung(id):
    """Export statement as PDF with numbered transaction list (landscape)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO

    # Register Unicode font
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        unicode_font = 'DejaVu'
        unicode_font_bold = 'DejaVu-Bold'
    except:
        unicode_font = 'Helvetica'
        unicode_font_bold = 'Helvetica-Bold'

    conn = get_db()

    # Get statement
    abrechnung = conn.execute('''
        SELECT a.*, k.name as konto_name, k.inhaber, k.kartennummer_letzte4
        FROM abrechnungen a
        LEFT JOIN konten k ON a.konto_id = k.id
        WHERE a.id = ?
    ''', (id,)).fetchone()

    if not abrechnung:
        conn.close()
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    # Get transactions with beleg info
    transaktionen = conn.execute('''
        SELECT t.*, b.datei_name as beleg_datei
        FROM transaktionen t
        LEFT JOIN belege b ON t.id = b.transaktion_id
        WHERE t.abrechnung_id = ?
        ORDER BY t.position ASC
    ''', (id,)).fetchall()

    conn.close()

    # Create PDF in landscape format
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=10)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=10, textColor=colors.grey)

    elements = []

    # Header
    elements.append(Paragraph(f"Kreditkartenabrechnung", title_style))
    karten_info = abrechnung['konto_name']
    if abrechnung['kartennummer_letzte4']:
        karten_info += f" (**** {abrechnung['kartennummer_letzte4']})"
    elements.append(Paragraph(f"{karten_info} - {abrechnung['periode']}", subtitle_style))
    if abrechnung['inhaber']:
        elements.append(Paragraph(f"Karteninhaber: {abrechnung['inhaber']}", subtitle_style))
    elements.append(Spacer(1, 10*mm))

    # Summary
    gesamtbetrag = abrechnung['gesamtbetrag'] or 0
    elements.append(Paragraph(f"<b>Gesamtbetrag:</b> {gesamtbetrag:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.'), styles['Normal']))
    elements.append(Paragraph(f"<b>Transaktionen:</b> {len(transaktionen)}", styles['Normal']))
    elements.append(Spacer(1, 8*mm))

    # Table header
    table_data = [['Nr.', 'Datum', 'Beschreibung', 'Betrag', 'Beleg']]

    # Table rows
    for t in transaktionen:
        pos = t['position'] or '-'
        datum = t['datum'] or '-'
        if datum and datum != '-':
            try:
                from datetime import datetime as dt
                d = dt.strptime(datum, '%Y-%m-%d')
                datum = d.strftime('%d.%m.%Y')
            except:
                pass

        beschreibung = t['beschreibung'] or ''
        if len(beschreibung) > 48:
            beschreibung = beschreibung[:45] + '...'

        betrag = t['betrag_eur'] or t['betrag'] or 0
        betrag_str = f"{betrag:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')

        beleg = t['beleg_datei'] or '-'
        if beleg != '-' and len(beleg) > 60:
            beleg = beleg[:57] + '...'

        table_data.append([
            f"{pos:02d}" if isinstance(pos, int) else pos,
            datum,
            beschreibung,
            betrag_str,
            beleg
        ])

    # Add total row
    total = sum((t['betrag_eur'] or t['betrag'] or 0) for t in transaktionen)
    total_str = f"{total:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
    table_data.append(['', '', 'Summe:', total_str, ''])

    # Create table (landscape: 297mm - 30mm margins = 267mm available)
    col_widths = [15*mm, 25*mm, 86*mm, 30*mm, 104*mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565c0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), unicode_font_bold),
        ('FONTNAME', (0, 1), (-1, -1), unicode_font),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
        ('FONTNAME', (2, -1), (3, -1), unicode_font_bold),
        ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f5f5f5')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))

    elements.append(table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    # Create filename
    periode_clean = abrechnung['periode'].replace(' ', '_').replace('.', '-')
    filename = f"Abrechnung_{periode_clean}.pdf"

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/abrechnungen/<int:id>/export-zip', methods=['GET'])
def export_abrechnung_zip(id):
    """Export statement as ZIP with PDF report, original statement, and receipts."""
    import zipfile
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO

    # Register Unicode font
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        unicode_font = 'DejaVu'
        unicode_font_bold = 'DejaVu-Bold'
    except:
        unicode_font = 'Helvetica'
        unicode_font_bold = 'Helvetica-Bold'

    conn = get_db()

    # Get statement
    abrechnung = conn.execute('''
        SELECT a.*, k.name as konto_name, k.inhaber, k.kartennummer_letzte4
        FROM abrechnungen a
        LEFT JOIN konten k ON a.konto_id = k.id
        WHERE a.id = ?
    ''', (id,)).fetchone()

    if not abrechnung:
        conn.close()
        return jsonify({'error': 'Abrechnung nicht gefunden'}), 404

    # Get transactions with beleg info
    transaktionen = conn.execute('''
        SELECT t.*, b.datei_name as beleg_datei, b.datei_pfad as beleg_pfad
        FROM transaktionen t
        LEFT JOIN belege b ON t.id = b.transaktion_id
        WHERE t.abrechnung_id = ?
        ORDER BY t.position ASC
    ''', (id,)).fetchall()

    conn.close()

    # Create ZIP in memory
    zip_buffer = BytesIO()
    periode_clean = (abrechnung['periode'] or 'export').replace(' ', '_').replace('.', '-').replace('/', '-')

    def add_file_utf8(zf, filepath, arcname):
        """Add file to ZIP with proper UTF-8 filename encoding."""
        with open(filepath, 'rb') as f:
            data = f.read()
        info = zipfile.ZipInfo(arcname)
        info.flag_bits |= 0x800  # UTF-8 filename flag
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, data)

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Add original statement PDF if exists
        if abrechnung['datei_pfad'] and os.path.exists(abrechnung['datei_pfad']):
            add_file_utf8(zf, abrechnung['datei_pfad'], f"00_Kreditkartenabrechnung_{periode_clean}.pdf")

        # 2. Add all receipts
        for t in transaktionen:
            if t['beleg_pfad'] and os.path.exists(t['beleg_pfad']):
                # Use the already renamed filename (with position prefix)
                add_file_utf8(zf, t['beleg_pfad'], f"Belege/{t['beleg_datei']}")

        # 3. Generate and add PDF report
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(A4), leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=10)
        subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=10, textColor=colors.grey)

        elements = []
        elements.append(Paragraph("Kreditkartenabrechnung", title_style))
        elements.append(Paragraph(f"{abrechnung['konto_name']} - {abrechnung['periode']}", subtitle_style))
        elements.append(Spacer(1, 10*mm))

        gesamtbetrag = abrechnung['gesamtbetrag'] or 0
        elements.append(Paragraph(f"<b>Gesamtbetrag:</b> {gesamtbetrag:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.'), styles['Normal']))
        elements.append(Paragraph(f"<b>Transaktionen:</b> {len(transaktionen)}", styles['Normal']))
        elements.append(Spacer(1, 8*mm))

        table_data = [['Nr.', 'Datum', 'Beschreibung', 'Betrag', 'Beleg']]

        for t in transaktionen:
            pos = t['position'] or '-'
            datum = t['datum'] or '-'
            if datum and datum != '-':
                try:
                    from datetime import datetime as dt
                    d = dt.strptime(datum, '%Y-%m-%d')
                    datum = d.strftime('%d.%m.%Y')
                except:
                    pass

            beschreibung = t['beschreibung'] or ''
            if len(beschreibung) > 48:
                beschreibung = beschreibung[:45] + '...'

            betrag = t['betrag_eur'] or t['betrag'] or 0
            betrag_str = f"{betrag:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')

            beleg = t['beleg_datei'] or '-'
            if beleg != '-' and len(beleg) > 60:
                beleg = beleg[:57] + '...'

            table_data.append([
                f"{pos:02d}" if isinstance(pos, int) else pos,
                datum,
                beschreibung,
                betrag_str,
                beleg
            ])

        total = sum((t['betrag_eur'] or t['betrag'] or 0) for t in transaktionen)
        total_str = f"{total:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
        table_data.append(['', '', 'Summe:', total_str, ''])

        col_widths = [15*mm, 25*mm, 86*mm, 30*mm, 104*mm]
        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565c0')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), unicode_font_bold),
            ('FONTNAME', (0, 1), (-1, -1), unicode_font),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
            ('FONTNAME', (2, -1), (3, -1), unicode_font_bold),
            ('BACKGROUND', (0, 1), (-1, -2), colors.HexColor('#f5f5f5')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#f5f5f5')]),
        ]))

        elements.append(table)
        doc.build(elements)
        pdf_buffer.seek(0)

        # Add PDF report with UTF-8 filename
        report_info = zipfile.ZipInfo(f"Transaktionsliste_{periode_clean}.pdf")
        report_info.flag_bits |= 0x800  # UTF-8 filename flag
        report_info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(report_info, pdf_buffer.read())

    zip_buffer.seek(0)
    filename = f"Kreditkartenabrechnung_{periode_clean}.zip"

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )


# --- Kategorien ---

@app.route('/api/kategorien', methods=['GET'])
def get_kategorien():
    """Get all available categories."""
    return jsonify(KATEGORIEN)


# --- Einstellungen ---

@app.route('/api/einstellungen', methods=['GET'])
def get_einstellungen():
    """Get application settings."""
    conn = get_db()
    einstellungen = conn.execute('SELECT * FROM einstellungen WHERE id = 1').fetchone()
    conn.close()
    return jsonify(dict(einstellungen) if einstellungen else {})


@app.route('/api/einstellungen', methods=['POST'])
def update_einstellungen():
    """Update application settings."""
    data = request.json
    conn = get_db()

    conn.execute('''
        UPDATE einstellungen
        SET name = ?, firma = ?, standard_kategorie = ?,
            auto_kategorisieren = ?, auto_matching = ?
        WHERE id = 1
    ''', (
        data.get('name'),
        data.get('firma'),
        data.get('standard_kategorie', 'sonstiges'),
        data.get('auto_kategorisieren', True),
        data.get('auto_matching', True)
    ))

    conn.commit()
    conn.close()
    return jsonify({'success': True})


# =============================================================================
# Main
# =============================================================================

# Initialize database on import (for Gunicorn)
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
