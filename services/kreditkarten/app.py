"""
Kreditkarten-Abgleich App - Flask Backend
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_restx import Api, Namespace, Resource, fields
from werkzeug.utils import secure_filename
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import anthropic
import sqlite3
import hashlib
import base64
import json
import os
import re
import io
import markdown
import glob as glob_module

load_dotenv()

app = Flask(__name__)

# Flask-RESTX API Setup (nur für /api/docs und /api/statistiken)
api = Api(app,
    version='1.0',
    title='Kreditkarten-App API',
    description='API für Kreditkarten-Abgleich und Belegverwaltung',
    doc='/api/docs',
    prefix='/api'  # Wichtig: API nur unter /api/* registrieren
)

# API Namespaces
statistiken_ns = Namespace('statistiken', description='Dashboard-Statistiken')
api.add_namespace(statistiken_ns, path='/statistiken')  # wird zu /api/statistiken durch prefix

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

# Reverse mapping: month name -> number
MONAT_NR = {name.lower(): nr for nr, name in MONAT_NAMEN.items()}


def periode_to_date(periode):
    """Convert period string like 'November 2025' to last day of month (YYYY-MM-DD)."""
    if not periode:
        return None
    parts = periode.lower().split()
    if len(parts) != 2:
        return None
    monat = MONAT_NR.get(parts[0])
    try:
        jahr = int(parts[1])
    except ValueError:
        return None
    if not monat:
        return None
    # Last day of month
    if monat == 12:
        return f'{jahr}-12-31'
    from datetime import date, timedelta
    next_month = date(jahr, monat + 1, 1)
    last_day = next_month - timedelta(days=1)
    return last_day.isoformat()

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
# Archiv-Funktionen
# =============================================================================

def get_archiv_path(konto_name, periode):
    """
    Erstellt den Archiv-Pfad: belege/archiv/{Konto}/{Periode}/
    Gibt den Pfad zurück und erstellt das Verzeichnis falls nötig.
    """
    konto_clean = (konto_name or 'Unbekannt').replace(' ', '_').replace('/', '-')
    periode_clean = (periode or 'Unbekannt').replace(' ', '_').replace('/', '-')

    archiv_path = os.path.join(BELEGE_DIR, 'archiv', konto_clean, periode_clean)
    os.makedirs(archiv_path, exist_ok=True)

    return archiv_path


def archive_beleg(beleg_pfad, konto_name, periode):
    """
    Verschiebt einen Beleg ins Archiv-Verzeichnis.
    Gibt den neuen Pfad zurück oder None bei Fehler.
    """
    import shutil

    if not beleg_pfad or not os.path.exists(beleg_pfad):
        return None

    archiv_dir = get_archiv_path(konto_name, periode)
    filename = os.path.basename(beleg_pfad)
    target_path = os.path.join(archiv_dir, filename)

    # Bei Namenskonflikt: Nummer anhängen
    if os.path.exists(target_path) and os.path.abspath(beleg_pfad) != os.path.abspath(target_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(archiv_dir, f"{base}_{counter}{ext}")
            counter += 1

    # Nur verschieben wenn nicht bereits im Zielverzeichnis
    if os.path.abspath(beleg_pfad) != os.path.abspath(target_path):
        try:
            shutil.move(beleg_pfad, target_path)
        except Exception as e:
            print(f"Archivierung fehlgeschlagen für {filename}: {e}")
            return None

    return target_path


def archive_abrechnung(abrechnung_id):
    """
    Archiviert alle Belege einer Abrechnung.
    Verschiebt Belege nach belege/archiv/{Konto}/{Periode}/
    Aktualisiert die Pfade in der Datenbank.
    Gibt die Anzahl archivierter Belege zurück.
    """
    conn = get_db()

    # Hole Abrechnung mit Konto-Info
    abrechnung = conn.execute('''
        SELECT a.*, k.name as konto_name
        FROM abrechnungen a
        LEFT JOIN konten k ON a.konto_id = k.id
        WHERE a.id = ?
    ''', (abrechnung_id,)).fetchone()

    if not abrechnung:
        conn.close()
        return 0

    konto_name = abrechnung['konto_name']
    periode = abrechnung['periode']

    # Hole alle Belege dieser Abrechnung
    belege = conn.execute('''
        SELECT b.id, b.datei_pfad
        FROM belege b
        JOIN transaktionen t ON b.transaktion_id = t.id
        WHERE t.abrechnung_id = ?
    ''', (abrechnung_id,)).fetchall()

    archived_count = 0

    for beleg in belege:
        if beleg['datei_pfad']:
            new_path = archive_beleg(beleg['datei_pfad'], konto_name, periode)
            if new_path and new_path != beleg['datei_pfad']:
                # Update Pfad in Datenbank
                conn.execute('UPDATE belege SET datei_pfad = ? WHERE id = ?',
                           (new_path, beleg['id']))
                archived_count += 1

    # Archiviere auch Bewirtungsbelege
    bewirtungsbelege = conn.execute('''
        SELECT bw.id, bw.datei_pfad
        FROM bewirtungsbelege bw
        JOIN transaktionen t ON bw.transaktion_id = t.id
        WHERE t.abrechnung_id = ?
    ''', (abrechnung_id,)).fetchall()

    for bw in bewirtungsbelege:
        if bw['datei_pfad']:
            new_path = archive_beleg(bw['datei_pfad'], konto_name, periode)
            if new_path and new_path != bw['datei_pfad']:
                conn.execute('UPDATE bewirtungsbelege SET datei_pfad = ? WHERE id = ?',
                           (new_path, bw['id']))
                archived_count += 1

    conn.commit()
    conn.close()

    return archived_count


# =============================================================================
# Database Functions
# =============================================================================

def get_db():
    """Get database connection with Row factory."""
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL-Modus für bessere Concurrent-Access Performance
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def db_execute_with_retry(conn, sql, params=None, max_retries=3, retry_delay=0.5):
    """Execute SQL with retry logic for database locked errors."""
    import time
    last_error = None
    for attempt in range(max_retries):
        try:
            if params:
                return conn.execute(sql, params)
            return conn.execute(sql)
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e):
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
            raise
    raise last_error


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
            auto_matching BOOLEAN DEFAULT 1,
            bewirtender_name TEXT,
            unterschrift_base64 TEXT
        );

        -- Personen für Bewirtungsbelege (Gästeliste)
        CREATE TABLE IF NOT EXISTS personen (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            firma TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Bewirtungsbelege
        CREATE TABLE IF NOT EXISTS bewirtungsbelege (
            id INTEGER PRIMARY KEY,
            transaktion_id INTEGER REFERENCES transaktionen(id),
            beleg_nr INTEGER,
            datum TEXT,
            restaurant TEXT,
            ort TEXT,
            anlass TEXT,
            bewirtender_name TEXT,
            betrag REAL,
            datei_pfad TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Teilnehmer für Bewirtungsbelege (n:m Relation)
        CREATE TABLE IF NOT EXISTS bewirtungsbeleg_teilnehmer (
            id INTEGER PRIMARY KEY,
            bewirtungsbeleg_id INTEGER REFERENCES bewirtungsbelege(id) ON DELETE CASCADE,
            person_id INTEGER REFERENCES personen(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    if not data or not data.get('name'):
        return jsonify({'error': 'Name ist erforderlich'}), 400
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


# --- Personen (Gäste für Bewirtungsbelege) ---

@app.route('/api/personen', methods=['GET'])
def get_personen():
    """Get all persons for guest list."""
    conn = get_db()
    personen = conn.execute('SELECT * FROM personen ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(p) for p in personen])


@app.route('/api/personen', methods=['POST'])
def create_person():
    """Create a new person."""
    data = request.json
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO personen (name, firma) VALUES (?, ?)',
        (data['name'], data.get('firma'))
    )
    person_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'id': person_id, 'success': True})


@app.route('/api/personen/<int:id>', methods=['PUT'])
def update_person(id):
    """Update a person."""
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE personen SET name = ?, firma = ? WHERE id = ?',
        (data['name'], data.get('firma'), id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/personen/<int:id>', methods=['DELETE'])
def delete_person(id):
    """Delete a person."""
    conn = get_db()
    conn.execute('DELETE FROM personen WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


# --- Einstellungen ---

@app.route('/api/einstellungen', methods=['GET'])
def get_einstellungen():
    """Get settings."""
    conn = get_db()
    einst = conn.execute('SELECT * FROM einstellungen WHERE id = 1').fetchone()
    conn.close()
    return jsonify(dict(einst) if einst else {})


@app.route('/api/einstellungen', methods=['PUT'])
def update_einstellungen():
    """Update settings."""
    data = request.json
    conn = get_db()

    # Build dynamic update query
    fields = []
    values = []
    for key in ['name', 'firma', 'bewirtender_name', 'unterschrift_base64']:
        if key in data:
            fields.append(f'{key} = ?')
            values.append(data[key])

    if fields:
        values.append(1)
        conn.execute(f"UPDATE einstellungen SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    conn.close()
    return jsonify({'success': True})


# --- Abrechnungen ---

@app.route('/api/abrechnungen', methods=['GET'])
def get_abrechnungen():
    """Get all statements, optionally filtered by account."""
    konto_id = request.args.get('konto_id')
    conn = get_db()

    # Query with transaction counts for status calculation
    base_query = '''
        SELECT a.*, k.name as konto_name,
            (SELECT COUNT(*) FROM transaktionen t WHERE t.abrechnung_id = a.id) as total_trans,
            (SELECT COUNT(*) FROM transaktionen t WHERE t.abrechnung_id = a.id AND t.status IN ('zugeordnet', 'ignoriert')) as done_trans
        FROM abrechnungen a
        LEFT JOIN konten k ON a.konto_id = k.id
    '''

    if konto_id:
        abrechnungen = conn.execute(
            base_query + ' WHERE a.konto_id = ? ORDER BY a.abrechnungsdatum DESC',
            (konto_id,)
        ).fetchall()
    else:
        abrechnungen = conn.execute(
            base_query + ' ORDER BY a.abrechnungsdatum DESC'
        ).fetchall()

    conn.close()

    # Calculate status dynamically
    result = []
    for a in abrechnungen:
        row = dict(a)
        total = row.pop('total_trans', 0)
        done = row.pop('done_trans', 0)
        if total > 0 and done == total:
            row['status'] = 'abgeschlossen'
        else:
            row['status'] = 'offen'
        result.append(row)

    return jsonify(result)


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

    # Save PDF (secure_filename prevents path traversal)
    content = file.read()
    safe_filename = secure_filename(file.filename)
    if not safe_filename:
        conn.close()
        return jsonify({'error': 'Ungültiger Dateiname'}), 400
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
    from parsers import parse_csv, detect_bank_format, parse_amex_pdf, validate_transaktionen, apply_corrections

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
        # Save PDF permanently (secure_filename prevents path traversal)
        safe_filename = secure_filename(original_filename)
        if not safe_filename:
            return jsonify({'error': 'Ungültiger Dateiname'}), 400
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

    # Validiere Transaktionen und korrigiere systematische Fehler
    auto_correct = request.form.get('auto_correct', 'true').lower() == 'true'
    validation = validate_transaktionen(transaktionen, periode)

    if validation['corrections'] and auto_correct:
        # Automatische Korrektur anwenden
        transaktionen = apply_corrections(transaktionen, validation['corrections'])
        # Re-validiere nach Korrektur
        validation = validate_transaktionen(transaktionen, periode)

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
    abrechnungsdatum = periode_to_date(periode)
    cursor = conn.execute('''
        INSERT INTO abrechnungen (konto_id, periode, abrechnungsdatum, gesamtbetrag, file_hash, datei_pfad, datei_name, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'offen')
    ''', (konto_id, periode, abrechnungsdatum, gesamtbetrag, file_hash, saved_filepath, original_filename))
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

    response = {
        'success': True,
        'id': abrechnung_id,
        'transaktionen': len(transaktionen),
        'gutschriften': gutschriften,
        'gesamtbetrag': gesamtbetrag
    }

    # Füge Validierungsinformationen hinzu
    if validation.get('warnings'):
        response['warnings'] = validation['warnings']
    if validation.get('corrections'):
        response['corrections_applied'] = validation['corrections']

    return jsonify(response)


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
    try:
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

    except Exception as e:
        return jsonify({'error': f'Kategorisierung fehlgeschlagen: {str(e)}'}), 500


# --- Belege ---

@app.route('/api/belege', methods=['GET'])
def get_belege():
    """Get all receipts with filters and pagination."""
    # Filter parameters
    konto_id = request.args.get('konto_id', type=int)
    von = request.args.get('von')  # YYYY-MM-DD
    bis = request.args.get('bis')  # YYYY-MM-DD
    status = request.args.get('status')  # zugeordnet / offen / alle
    nur_unzugeordnet = request.args.get('unzugeordnet') == 'true'  # Legacy support

    # Pagination
    limit = request.args.get('limit', type=int, default=25)
    offset = request.args.get('offset', type=int, default=0)

    # Sorting
    sort_by = request.args.get('sort_by', 'datum')  # datum, haendler, betrag, konto, status
    sort_order = request.args.get('sort_order', 'desc')  # asc, desc

    # Map sort_by to actual column names
    sort_columns = {
        'datum': 'COALESCE(t.datum, b.created_at)',
        'haendler': 'COALESCE(t.haendler, b.datei_name)',
        'betrag': 'COALESCE(t.betrag, 0)',
        'konto': 'COALESCE(k.name, "")',
        'status': 'CASE WHEN b.transaktion_id IS NOT NULL THEN 1 ELSE 0 END'
    }
    order_column = sort_columns.get(sort_by, sort_columns['datum'])
    order_dir = 'ASC' if sort_order.lower() == 'asc' else 'DESC'

    conn = get_db()

    # Build query with filters
    conditions = []
    params = []

    # Status filter
    if nur_unzugeordnet or status == 'offen':
        conditions.append("b.transaktion_id IS NULL")
    elif status == 'zugeordnet':
        conditions.append("b.transaktion_id IS NOT NULL")

    # Konto filter (via transaktion -> abrechnung -> konto)
    if konto_id:
        conditions.append("a.konto_id = ?")
        params.append(konto_id)

    # Date range filter (from extrahierte_daten JSON or transaktion datum)
    if von:
        conditions.append("(t.datum >= ? OR b.created_at >= ?)")
        params.extend([von, von])
    if bis:
        conditions.append("(t.datum <= ? OR b.created_at <= ?)")
        params.extend([bis, bis])

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Count total
    count_query = f'''
        SELECT COUNT(*) FROM belege b
        LEFT JOIN transaktionen t ON b.transaktion_id = t.id
        LEFT JOIN abrechnungen a ON t.abrechnung_id = a.id
        WHERE {where_clause}
    '''
    total = conn.execute(count_query, params).fetchone()[0]

    # Get belege with details
    query = f'''
        SELECT
            b.id,
            b.datei_name,
            b.datei_pfad,
            b.file_hash,
            b.extrahierte_daten,
            b.match_confidence,
            b.transaktion_id,
            b.created_at,
            t.datum,
            t.haendler,
            t.betrag,
            t.beschreibung as transaktion_beschreibung,
            a.periode,
            k.name as konto_name
        FROM belege b
        LEFT JOIN transaktionen t ON b.transaktion_id = t.id
        LEFT JOIN abrechnungen a ON t.abrechnung_id = a.id
        LEFT JOIN konten k ON a.konto_id = k.id
        WHERE {where_clause}
        ORDER BY {order_column} {order_dir}
        LIMIT ? OFFSET ?
    '''
    params.extend([limit, offset])
    belege_raw = conn.execute(query, params).fetchall()
    conn.close()

    # Format response
    belege = []
    for b in belege_raw:
        beleg = dict(b)
        # Parse extrahierte_daten if available
        if beleg.get('extrahierte_daten'):
            try:
                extracted = json.loads(beleg['extrahierte_daten'])
                beleg['extracted_betrag'] = extracted.get('betrag')
                beleg['extracted_datum'] = extracted.get('datum')
                beleg['extracted_haendler'] = extracted.get('haendler')
            except json.JSONDecodeError:
                pass
        # Determine display values (prefer transaktion data, fallback to extracted)
        beleg['display_datum'] = beleg.get('datum') or beleg.get('extracted_datum') or beleg.get('created_at', '')[:10]
        beleg['display_haendler'] = beleg.get('haendler') or beleg.get('extracted_haendler') or beleg.get('datei_name', '')
        beleg['display_betrag'] = beleg.get('betrag') or beleg.get('extracted_betrag')
        beleg['status'] = 'zugeordnet' if beleg.get('transaktion_id') else 'offen'
        belege.append(beleg)

    return jsonify({
        'belege': belege,
        'total': total,
        'limit': limit,
        'offset': offset
    })


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


@app.route('/api/belege/<int:id>', methods=['GET'])
def get_beleg(id):
    """Get a single receipt by ID."""
    conn = get_db()
    beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (id,)).fetchone()
    conn.close()

    if not beleg:
        return jsonify({'error': 'Beleg nicht gefunden'}), 404

    # Parse extracted data
    try:
        extracted = json.loads(beleg['extrahierte_daten'] or '{}')
    except json.JSONDecodeError:
        extracted = {}

    return jsonify({
        'id': beleg['id'],
        'datei_name': beleg['datei_name'],
        'datei_pfad': beleg['datei_pfad'],
        'file_hash': beleg['file_hash'],
        'transaktion_id': beleg['transaktion_id'],
        'match_typ': beleg['match_typ'],
        'match_confidence': beleg['match_confidence'],
        'created_at': beleg['created_at'],
        'extrahierte_daten': beleg['extrahierte_daten'],  # Keep as JSON string for frontend
        'betrag': extracted.get('betrag'),
        'datum': extracted.get('datum'),
        'haendler': extracted.get('haendler'),
        'waehrung': extracted.get('waehrung', 'EUR'),
        'kategorie_vorschlag': extracted.get('kategorie_vorschlag'),
        'rechnungsnummer': extracted.get('rechnungsnummer'),
        'mwst': extracted.get('mwst'),
        'ocr_text': extracted.get('ocr_text', '')
    })


@app.route('/api/belege/<int:id>', methods=['DELETE'])
def delete_beleg(id):
    """Delete a receipt."""
    conn = get_db()
    beleg = conn.execute('SELECT * FROM belege WHERE id = ?', (id,)).fetchone()

    if not beleg:
        conn.close()
        return jsonify({'error': 'Beleg nicht gefunden'}), 404

    # Check if assigned to a transaction
    if beleg['transaktion_id']:
        # Update transaction status back to 'offen'
        conn.execute('''
            UPDATE transaktionen SET status = 'offen'
            WHERE id = ? AND status = 'zugeordnet'
        ''', (beleg['transaktion_id'],))

    # Delete from database
    conn.execute('DELETE FROM belege WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    # Delete file if exists
    filepath = beleg['datei_pfad']
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception as e:
            app.logger.warning(f"Datei konnte nicht gelöscht werden: {e}")

    return jsonify({
        'success': True,
        'message': 'Beleg gelöscht',
        'was_assigned': beleg['transaktion_id'] is not None
    })


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

    # Save file (secure_filename prevents path traversal)
    filename = secure_filename(file.filename)
    if not filename:
        conn.close()
        return jsonify({'error': 'Ungültiger Dateiname'}), 400
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

    # Save to database with error handling
    beleg_id = None
    error_response = None
    try:
        cursor = db_execute_with_retry(conn, '''
            INSERT INTO belege (datei_name, datei_pfad, file_hash, extrahierte_daten)
            VALUES (?, ?, ?, ?)
        ''', (filename, filepath, file_hash, json.dumps(extracted)))
        beleg_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        # Race condition: another request inserted the same hash
        conn.close()
        conn = get_db()
        existing = conn.execute(
            'SELECT id FROM belege WHERE file_hash = ?', (file_hash,)
        ).fetchone()
        # Clean up the saved file since we won't use it
        if os.path.exists(filepath):
            os.remove(filepath)
        if existing:
            error_response = (jsonify({'error': 'Dieser Beleg existiert bereits', 'id': existing['id']}), 409)
        else:
            error_response = (jsonify({'error': 'Beleg konnte nicht gespeichert werden (Duplikat)'}), 409)
    except sqlite3.OperationalError as e:
        app.logger.error(f"Database error during beleg upload: {e}")
        error_response = (jsonify({'error': 'Datenbank vorübergehend nicht verfügbar, bitte erneut versuchen'}), 503)
    finally:
        conn.close()

    if error_response:
        return error_response

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

            try:
                db_execute_with_retry(conn, '''
                    UPDATE belege
                    SET transaktion_id = ?, match_typ = 'auto', match_confidence = ?,
                        datei_name = ?, datei_pfad = ?
                    WHERE id = ?
                ''', (best_match['id'], best_score, new_filename, new_filepath, beleg['id']))

                db_execute_with_retry(conn, '''
                    UPDATE transaktionen SET status = 'zugeordnet' WHERE id = ?
                ''', (best_match['id'],))
            except sqlite3.OperationalError as e:
                app.logger.error(f"Database error during auto-match update: {e}")
                # Skip this match but continue with others
                continue

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

    try:
        conn.commit()
    except sqlite3.OperationalError as e:
        app.logger.error(f"Database error during auto-match commit: {e}")
        return jsonify({'error': 'Datenbank vorübergehend nicht verfügbar', 'partial_matches': matches_found}), 503
    finally:
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

    # Get Bewirtungsbelege for this statement
    bewirtungsbelege = conn.execute('''
        SELECT bw.*, t.position as transaktion_position
        FROM bewirtungsbelege bw
        JOIN transaktionen t ON bw.transaktion_id = t.id
        WHERE t.abrechnung_id = ?
        ORDER BY t.position ASC
    ''', (id,)).fetchall()

    conn.close()

    # Create ZIP in memory
    zip_buffer = BytesIO()
    periode_clean = (abrechnung['periode'] or 'export').replace(' ', '_').replace('.', '-').replace('/', '-')
    konto_clean = (abrechnung['konto_name'] or 'Kreditkarte').replace(' ', '_').replace('.', '-').replace('/', '-')
    base_name = f"{konto_clean}_{periode_clean}"

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
            add_file_utf8(zf, abrechnung['datei_pfad'], f"{base_name}/00_Abrechnung_{periode_clean}.pdf")

        # 2. Add all receipts
        for t in transaktionen:
            if t['beleg_pfad'] and os.path.exists(t['beleg_pfad']):
                # Use the already renamed filename (with position prefix)
                add_file_utf8(zf, t['beleg_pfad'], f"{base_name}/Belege/{t['beleg_datei']}")

        # 3. Add all Bewirtungsbelege
        for bw in bewirtungsbelege:
            if bw['datei_pfad'] and os.path.exists(bw['datei_pfad']):
                # Extract filename from path
                bw_filename = os.path.basename(bw['datei_pfad'])
                add_file_utf8(zf, bw['datei_pfad'], f"{base_name}/Bewirtungsbelege/{bw_filename}")

        # 4. Generate and add PDF report
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
        report_info = zipfile.ZipInfo(f"{base_name}/Transaktionsliste_{periode_clean}.pdf")
        report_info.flag_bits |= 0x800  # UTF-8 filename flag
        report_info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(report_info, pdf_buffer.read())

    zip_buffer.seek(0)
    filename = f"{base_name}.zip"

    # Archiviere Belege nach erfolgreichem Export
    archive = request.args.get('archive', 'true').lower() == 'true'
    if archive:
        archived_count = archive_abrechnung(id)
        if archived_count > 0:
            app.logger.info(f"Archiviert: {archived_count} Belege für {base_name}")

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=filename
    )


# --- Archivierung ---

@app.route('/api/abrechnungen/<int:id>/archivieren', methods=['POST'])
def archiviere_abrechnung(id):
    """Archiviert alle Belege einer Abrechnung manuell."""
    archived_count = archive_abrechnung(id)

    if archived_count > 0:
        return jsonify({
            'success': True,
            'message': f'{archived_count} Beleg(e) archiviert',
            'archived_count': archived_count
        })
    else:
        return jsonify({
            'success': True,
            'message': 'Keine Belege zum Archivieren gefunden',
            'archived_count': 0
        })


# --- Kategorien ---

@app.route('/api/kategorien', methods=['GET'])
def get_kategorien():
    """Get all available categories."""
    return jsonify(KATEGORIEN)


# --- Bewirtungsbelege ---

@app.route('/api/transaktionen/<int:id>/bewirtungsbeleg', methods=['POST'])
def create_bewirtungsbeleg(id):
    """Generate Bewirtungsbeleg PDF for a restaurant transaction."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO
    import base64
    import json
    import os

    # Register Unicode font
    try:
        pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))
        unicode_font = 'DejaVu'
        unicode_font_bold = 'DejaVu-Bold'
    except:
        unicode_font = 'Helvetica'
        unicode_font_bold = 'Helvetica-Bold'

    data = request.json
    conn = get_db()

    # Get transaction
    transaktion = conn.execute('SELECT * FROM transaktionen WHERE id = ?', (id,)).fetchone()
    if not transaktion:
        conn.close()
        return jsonify({'error': 'Transaktion nicht gefunden'}), 404

    # Get settings for bewirtender name and signature
    einst = conn.execute('SELECT * FROM einstellungen WHERE id = 1').fetchone()

    # Use transaction position as Bewirtungsbeleg number
    beleg_nr = transaktion['position'] or 1

    # Parse data
    datum = data.get('datum', transaktion['datum'])
    if datum and '-' in datum:
        try:
            from datetime import datetime as dt
            d = dt.strptime(datum, '%Y-%m-%d')
            datum_formatted = d.strftime('%d.%m.%Y')
        except:
            datum_formatted = datum
    else:
        datum_formatted = datum

    restaurant = data.get('restaurant', transaktion['haendler'] or transaktion['beschreibung'] or '')
    ort = data.get('ort', '')
    anlass = data.get('anlass', 'Geschäftliche Besprechung')
    teilnehmer = data.get('teilnehmer', [])  # List of {name, firma}
    betrag = transaktion['betrag_eur'] or transaktion['betrag'] or 0
    bewirtender_name = data.get('bewirtender_name') or (einst['bewirtender_name'] if einst else None) or ''
    unterschrift_base64 = data.get('unterschrift_base64') or (einst['unterschrift_base64'] if einst else None)

    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', fontName=unicode_font_bold, fontSize=18, spaceAfter=5, textColor=colors.HexColor('#333333'))
    subtitle_style = ParagraphStyle('Subtitle', fontName=unicode_font, fontSize=10, textColor=colors.grey, spaceAfter=15)
    label_style = ParagraphStyle('Label', fontName=unicode_font_bold, fontSize=10, textColor=colors.HexColor('#333333'))
    normal_style = ParagraphStyle('Normal', fontName=unicode_font, fontSize=10, leading=14)
    footer_style = ParagraphStyle('Footer', fontName=unicode_font, fontSize=8, textColor=colors.grey)

    elements = []

    # Header
    elements.append(Paragraph(f"Bewirtungsbeleg Nr. {beleg_nr:02d}", title_style))
    elements.append(Paragraph("gemäß § 4 Abs. 5 Nr. 2 EStG", subtitle_style))
    elements.append(Spacer(1, 5*mm))

    # Main data table
    main_data = [
        [Paragraph("<b>Tag der Bewirtung:</b>", label_style), Paragraph(datum_formatted, normal_style)],
        [Paragraph("<b>Ort (Name und Anschrift):</b>", label_style), Paragraph(f"{restaurant}\n{ort}" if ort else restaurant, normal_style)],
    ]

    main_table = Table(main_data, colWidths=[60*mm, 110*mm])
    main_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
    ]))
    elements.append(main_table)
    elements.append(Spacer(1, 8*mm))

    # Guest list
    elements.append(Paragraph("<b>Bewirtete Personen:</b>", label_style))
    elements.append(Spacer(1, 3*mm))

    guest_data = [[Paragraph("<b>Name</b>", label_style), Paragraph("<b>Firma/Funktion</b>", label_style)]]
    for t in teilnehmer:
        guest_data.append([
            Paragraph(t.get('name', ''), normal_style),
            Paragraph(t.get('firma', ''), normal_style)
        ])
    # Add empty rows for manual completion (minimum 4 rows total)
    while len(guest_data) < 5:
        guest_data.append(['', ''])

    guest_table = Table(guest_data, colWidths=[85*mm, 85*mm])
    guest_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f5f5f5')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('MINROWHEIGHT', (0, 1), (-1, -1), 8*mm),
    ]))
    elements.append(guest_table)
    elements.append(Spacer(1, 8*mm))

    # Purpose
    elements.append(Paragraph("<b>Anlass der Bewirtung:</b>", label_style))
    elements.append(Spacer(1, 2*mm))
    anlass_table = Table([[Paragraph(anlass, normal_style)]], colWidths=[170*mm])
    anlass_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('MINROWHEIGHT', (0, 0), (-1, -1), 12*mm),
    ]))
    elements.append(anlass_table)
    elements.append(Spacer(1, 8*mm))

    # Amount
    betrag_str = f"{betrag:,.2f} €".replace(',', 'X').replace('.', ',').replace('X', '.')
    amount_data = [[Paragraph("<b>Höhe der Aufwendungen:</b>", label_style), Paragraph(betrag_str, normal_style)]]
    amount_table = Table(amount_data, colWidths=[60*mm, 110*mm])
    amount_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#f5f5f5')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(amount_table)
    elements.append(Spacer(1, 15*mm))

    # Signature section
    elements.append(Paragraph("<b>Unterschrift des Bewirtenden:</b>", label_style))
    elements.append(Spacer(1, 3*mm))

    # Signature image or blank line
    if unterschrift_base64:
        try:
            sig_data = base64.b64decode(unterschrift_base64.split(',')[1] if ',' in unterschrift_base64 else unterschrift_base64)
            sig_buffer = BytesIO(sig_data)
            sig_img = Image(sig_buffer, width=50*mm, height=15*mm)
            elements.append(sig_img)
        except:
            elements.append(Spacer(1, 15*mm))
    else:
        elements.append(Spacer(1, 15*mm))

    # Signature line
    sig_line = Table([['_' * 60]], colWidths=[170*mm])
    sig_line.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    elements.append(sig_line)
    elements.append(Paragraph(f"Datum, Unterschrift: {bewirtender_name}", normal_style))
    elements.append(Spacer(1, 15*mm))

    # Footer notice
    elements.append(Paragraph(
        "<i>Hinweis: Bitte Originalbeleg anheften. Bei Bewirtungen in Gaststätten ist die Rechnung des Gastwirts beizufügen.</i>",
        footer_style
    ))

    # Build PDF
    doc.build(elements)
    pdf_data = buffer.getvalue()
    buffer.close()

    # Save to database and file
    restaurant_clean = re.sub(r'[^\w\s-]', '', restaurant).replace(' ', '_')[:30]
    filename = f"{beleg_nr:02d}_{datum.replace('-', '')}_{restaurant_clean}_Bewirtungsbeleg.pdf"

    # Save to exports directory
    export_dir = '/app/exports/bewirtungsbelege'
    os.makedirs(export_dir, exist_ok=True)
    filepath = os.path.join(export_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(pdf_data)

    # Save Bewirtungsbeleg record
    cursor = conn.execute('''
        INSERT INTO bewirtungsbelege (transaktion_id, beleg_nr, datum, restaurant, ort, anlass, bewirtender_name, betrag, datei_pfad)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (id, beleg_nr, datum, restaurant, ort, anlass, bewirtender_name, betrag, filepath))
    bewirtungsbeleg_id = cursor.lastrowid

    # Save teilnehmer relations
    for t in teilnehmer:
        # Find or create person
        person = conn.execute('SELECT id FROM personen WHERE name = ?', (t['name'],)).fetchone()
        if person:
            person_id = person['id']
            # Update firma if provided
            if t.get('firma'):
                conn.execute('UPDATE personen SET firma = ? WHERE id = ?', (t['firma'], person_id))
        else:
            cursor = conn.execute('INSERT INTO personen (name, firma) VALUES (?, ?)', (t['name'], t.get('firma')))
            person_id = cursor.lastrowid

        # Link to Bewirtungsbeleg
        conn.execute('INSERT INTO bewirtungsbeleg_teilnehmer (bewirtungsbeleg_id, person_id) VALUES (?, ?)',
                     (bewirtungsbeleg_id, person_id))

    conn.commit()
    conn.close()

    # Return PDF
    return send_file(
        BytesIO(pdf_data),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/transaktionen/<int:id>/bewirtungsbeleg', methods=['GET'])
def get_bewirtungsbeleg(id):
    """Get existing Bewirtungsbeleg for a transaction with participants."""
    conn = get_db()
    beleg = conn.execute('SELECT * FROM bewirtungsbelege WHERE transaktion_id = ?', (id,)).fetchone()

    if not beleg:
        conn.close()
        return jsonify(None)

    # Get teilnehmer from junction table
    teilnehmer = conn.execute('''
        SELECT p.id, p.name, p.firma
        FROM bewirtungsbeleg_teilnehmer bt
        JOIN personen p ON bt.person_id = p.id
        WHERE bt.bewirtungsbeleg_id = ?
        ORDER BY p.name
    ''', (beleg['id'],)).fetchall()
    conn.close()

    result = dict(beleg)
    result['teilnehmer'] = [dict(t) for t in teilnehmer]
    return jsonify(result)


# =============================================================================
# Handbuch / Hilfe
# =============================================================================

HANDBUCH_DIR = os.path.join(os.path.dirname(__file__), 'docs', 'handbuch')

HANDBUCH_KAPITEL = [
    {'id': '01-erste-schritte', 'titel': 'Erste Schritte', 'datei': '01-erste-schritte.md'},
    {'id': '02-import', 'titel': 'Abrechnungen importieren', 'datei': '02-import.md'},
    {'id': '03-belege-zuordnen', 'titel': 'Belege zuordnen', 'datei': '03-belege-zuordnen.md'},
    {'id': '04-kategorisierung', 'titel': 'Kategorisierung', 'datei': '04-kategorisierung.md'},
    {'id': '05-bewirtungsbelege', 'titel': 'Bewirtungsbelege', 'datei': '05-bewirtungsbelege.md'},
    {'id': '06-export-archivierung', 'titel': 'Export & Archivierung', 'datei': '06-export-archivierung.md'},
    {'id': '07-konten-verwalten', 'titel': 'Konten verwalten', 'datei': '07-konten-verwalten.md'},
]


@app.route('/api/hilfe/kapitel')
def get_handbuch_kapitel():
    """Gibt die Liste aller Handbuch-Kapitel zurück."""
    return jsonify(HANDBUCH_KAPITEL)


@app.route('/api/hilfe/kapitel/<kapitel_id>')
def get_handbuch_inhalt(kapitel_id):
    """Gibt den HTML-Inhalt eines Kapitels zurück."""
    kapitel = next((k for k in HANDBUCH_KAPITEL if k['id'] == kapitel_id), None)
    if not kapitel:
        return jsonify({'error': 'Kapitel nicht gefunden'}), 404

    datei_pfad = os.path.join(HANDBUCH_DIR, kapitel['datei'])
    if not os.path.exists(datei_pfad):
        return jsonify({'error': 'Datei nicht gefunden'}), 404

    with open(datei_pfad, 'r', encoding='utf-8') as f:
        md_content = f.read()

    html_content = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
    return jsonify({
        'id': kapitel['id'],
        'titel': kapitel['titel'],
        'html': html_content
    })


@app.route('/api/hilfe/pdf')
def get_handbuch_pdf():
    """Generiert das komplette Handbuch als PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from io import BytesIO
    import re

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                           leftMargin=2*cm, rightMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Titel', fontSize=24, spaceAfter=30, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Kapitel', fontSize=18, spaceBefore=20, spaceAfter=15, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Unterkapitel', fontSize=14, spaceBefore=15, spaceAfter=10, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Text', fontSize=11, spaceAfter=8, leading=14))
    styles.add(ParagraphStyle(name='ListItem', fontSize=11, spaceAfter=4, leftIndent=20, leading=14))

    story = []

    # Titelseite
    story.append(Spacer(1, 5*cm))
    story.append(Paragraph('Kreditkarten-Abgleich App', styles['Titel']))
    story.append(Paragraph('Benutzerhandbuch', styles['Kapitel']))
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph(f'Stand: {datetime.now().strftime("%d.%m.%Y")}', styles['Text']))
    story.append(PageBreak())

    # Inhaltsverzeichnis
    story.append(Paragraph('Inhaltsverzeichnis', styles['Kapitel']))
    for i, kapitel in enumerate(HANDBUCH_KAPITEL, 1):
        story.append(Paragraph(f'{i}. {kapitel["titel"]}', styles['Text']))
    story.append(PageBreak())

    # Kapitel
    for kapitel in HANDBUCH_KAPITEL:
        datei_pfad = os.path.join(HANDBUCH_DIR, kapitel['datei'])
        if not os.path.exists(datei_pfad):
            continue

        with open(datei_pfad, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # Einfaches Markdown-Parsing für PDF
        lines = md_content.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                story.append(Spacer(1, 0.3*cm))
            elif line.startswith('# '):
                story.append(Paragraph(line[2:], styles['Kapitel']))
            elif line.startswith('## '):
                story.append(Paragraph(line[3:], styles['Unterkapitel']))
            elif line.startswith('### '):
                story.append(Paragraph(f'<b>{line[4:]}</b>', styles['Text']))
            elif line.startswith('- '):
                story.append(Paragraph(f'• {line[2:]}', styles['ListItem']))
            elif line.startswith('|'):
                continue  # Tabellen überspringen für Einfachheit
            elif line.startswith('```'):
                continue  # Code-Blöcke überspringen
            else:
                # Inline-Formatierung
                line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
                line = re.sub(r'\*(.+?)\*', r'<i>\1</i>', line)
                if line:
                    story.append(Paragraph(line, styles['Text']))

        story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='Kreditkarten-App_Benutzerhandbuch.pdf'
    )


# =============================================================================
# Flask-RESTX API Endpoints
# =============================================================================

# API Models für Swagger-Dokumentation
kategorie_stat_model = api.model('KategorieStat', {
    'name': fields.String(description='Kategorie-Schlüssel'),
    'label': fields.String(description='Anzeigename'),
    'summe': fields.Float(description='Gesamtbetrag'),
    'anzahl': fields.Integer(description='Anzahl Transaktionen')
})

monat_stat_model = api.model('MonatStat', {
    'monat': fields.String(description='Monat im Format YYYY-MM'),
    'summe': fields.Float(description='Gesamtbetrag')
})

haendler_stat_model = api.model('HaendlerStat', {
    'name': fields.String(description='Händlername'),
    'summe': fields.Float(description='Gesamtbetrag'),
    'anzahl': fields.Integer(description='Anzahl Transaktionen')
})

statistiken_model = api.model('Statistiken', {
    'zeitraum': fields.Nested(api.model('Zeitraum', {
        'von': fields.String(description='Startdatum'),
        'bis': fields.String(description='Enddatum')
    })),
    'kategorien': fields.List(fields.Nested(kategorie_stat_model)),
    'monatlich': fields.List(fields.Nested(monat_stat_model)),
    'haendler': fields.List(fields.Nested(haendler_stat_model))
})


@statistiken_ns.route('')
class StatistikenResource(Resource):
    @statistiken_ns.doc('get_statistiken',
        params={
            'konto_id': 'Filter auf ein Konto (optional)',
            'jahr': 'Jahr, z.B. 2026 (optional)',
            'monate': 'Anzahl Monate zurück (default: 12)'
        })
    @statistiken_ns.marshal_with(statistiken_model)
    def get(self):
        """Liefert aggregierte Statistiken für das Dashboard"""
        konto_id = request.args.get('konto_id', type=int)
        jahr = request.args.get('jahr', type=int)
        monate = request.args.get('monate', type=int, default=12)

        conn = get_db()

        # Zeitraum berechnen
        if jahr:
            von = f"{jahr}-01-01"
            bis = f"{jahr}-12-31"
        else:
            from datetime import timedelta
            bis_date = datetime.now()
            von_date = bis_date - timedelta(days=monate * 30)
            von = von_date.strftime('%Y-%m-%d')
            bis = bis_date.strftime('%Y-%m-%d')

        # Basis-Query-Bedingungen
        conditions = ["t.datum >= ? AND t.datum <= ?"]
        params = [von, bis]

        if konto_id:
            conditions.append("a.konto_id = ?")
            params.append(konto_id)

        where_clause = " AND ".join(conditions)

        # 1. Kategorien-Statistik
        kategorien_query = f"""
            SELECT
                COALESCE(t.kategorie, 'sonstiges') as name,
                SUM(t.betrag) as summe,
                COUNT(*) as anzahl
            FROM transaktionen t
            JOIN abrechnungen a ON t.abrechnung_id = a.id
            WHERE {where_clause}
            GROUP BY t.kategorie
            ORDER BY summe DESC
        """
        kategorien_raw = conn.execute(kategorien_query, params).fetchall()
        kategorien = []
        for k in kategorien_raw:
            name = k['name'] or 'sonstiges'
            label = KATEGORIEN.get(name, name.replace('_', ' ').title())
            kategorien.append({
                'name': name,
                'label': label,
                'summe': round(k['summe'] or 0, 2),
                'anzahl': k['anzahl']
            })

        # 2. Monatliche Statistik
        monatlich_query = f"""
            SELECT
                strftime('%Y-%m', t.datum) as monat,
                SUM(t.betrag) as summe
            FROM transaktionen t
            JOIN abrechnungen a ON t.abrechnung_id = a.id
            WHERE {where_clause}
            GROUP BY strftime('%Y-%m', t.datum)
            ORDER BY monat
        """
        monatlich_raw = conn.execute(monatlich_query, params).fetchall()
        monatlich = [{
            'monat': m['monat'],
            'summe': round(m['summe'] or 0, 2)
        } for m in monatlich_raw]

        # 3. Top Händler
        haendler_query = f"""
            SELECT
                t.haendler as name,
                SUM(t.betrag) as summe,
                COUNT(*) as anzahl
            FROM transaktionen t
            JOIN abrechnungen a ON t.abrechnung_id = a.id
            WHERE {where_clause} AND t.haendler IS NOT NULL AND t.haendler != ''
            GROUP BY t.haendler
            ORDER BY summe DESC
            LIMIT 10
        """
        haendler_raw = conn.execute(haendler_query, params).fetchall()
        haendler = [{
            'name': h['name'],
            'summe': round(h['summe'] or 0, 2),
            'anzahl': h['anzahl']
        } for h in haendler_raw]

        conn.close()

        return {
            'zeitraum': {'von': von, 'bis': bis},
            'kategorien': kategorien,
            'monatlich': monatlich,
            'haendler': haendler
        }


# =============================================================================
# Main
# =============================================================================

# Initialize database on import (for Gunicorn)
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
