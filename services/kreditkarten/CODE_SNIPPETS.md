# Wiederverwendbare Code-Snippets

## 1. Flask App Grundgerüst

```python
from flask import Flask, render_template, request, jsonify, send_file
from datetime import datetime
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import anthropic
import sqlite3
import os
import json

load_dotenv()

app = Flask(__name__)
DATA_DIR = os.environ.get('DATA_DIR', './data')

# Health Check
@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': 'connected' if check_db() else 'error'
    })
```

## 2. Datenbank-Initialisierung

```python
def get_db():
    db_path = os.path.join(DATA_DIR, 'app.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS ...
    ''')
    conn.commit()
    conn.close()
```

## 3. Verschlüsselung

```python
def get_cipher():
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
    return get_cipher().encrypt(data.encode()).decode()

def decrypt(encrypted):
    return get_cipher().decrypt(encrypted.encode()).decode()
```

## 4. Claude API Integration

```python
def get_anthropic_client():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)

def extract_with_ai(text, image_base64=None, prompt_template=""):
    client = get_anthropic_client()

    content = []
    if image_base64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_base64
            }
        })
    content.append({"type": "text", "text": prompt_template.format(text=text)})

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}]
    )

    response_text = message.content[0].text
    # JSON extrahieren
    if '```json' in response_text:
        response_text = response_text.split('```json')[1].split('```')[0]
    elif '```' in response_text:
        response_text = response_text.split('```')[1].split('```')[0]

    return json.loads(response_text.strip())
```

## 5. Währungsumrechnung (EZB)

```python
import requests
import re

FALLBACK_RATES = {'USD': 0.92, 'CHF': 1.08, 'GBP': 1.17, 'DKK': 0.134}

def get_exchange_rates():
    try:
        response = requests.get(
            'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml',
            timeout=5
        )
        rates = {'EUR': 1.0}
        for match in re.finditer(r"currency='(\w+)' rate='([\d.]+)'", response.text):
            currency, rate = match.groups()
            rates[currency] = 1.0 / float(rate)
        return rates
    except:
        return FALLBACK_RATES

def convert_to_eur(amount, currency):
    if currency == 'EUR':
        return amount
    rates = get_exchange_rates()
    return amount * rates.get(currency, 1.0)
```

## 6. Datums-Parsing

```python
from datetime import datetime

MONAT_KURZ = {
    'jan': 1, 'feb': 2, 'mär': 3, 'mar': 3, 'apr': 4,
    'mai': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'okt': 10, 'nov': 11, 'dez': 12
}

def parse_datum(datum_str):
    """Versucht verschiedene Datumsformate zu parsen."""
    if not datum_str:
        return None

    formats = ['%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d.%m.%y']
    for fmt in formats:
        try:
            return datetime.strptime(datum_str.strip(), fmt)
        except ValueError:
            continue
    return None

def sort_by_date(items, date_field='datum'):
    """Sortiert eine Liste nach Datum."""
    def get_date(item):
        d = parse_datum(item.get(date_field, ''))
        return d if d else datetime.min
    return sorted(items, key=get_date)
```

## 7. Cache-Management

```python
import hashlib
import json

CACHE_FILE = os.path.join(DATA_DIR, '.cache.json')

def get_file_hash(content):
    return hashlib.md5(content).hexdigest()

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def get_cached_or_process(file_content, process_func):
    cache = load_cache()
    file_hash = get_file_hash(file_content)

    if file_hash in cache:
        return cache[file_hash], True  # cached=True

    result = process_func(file_content)
    cache[file_hash] = result
    save_cache(cache)
    return result, False  # cached=False
```

## 8. Excel-Export

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
import io

def generate_excel(data, columns, title="Export"):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel limit

    # Styles
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill('solid', fgColor='333333')

    # Header
    for col, (key, label) in enumerate(columns.items(), 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = header_font
        cell.fill = header_fill

    # Data
    for row_idx, item in enumerate(data, 2):
        for col_idx, key in enumerate(columns.keys(), 1):
            ws.cell(row=row_idx, column=col_idx, value=item.get(key, ''))

    # Column widths
    for col in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 15

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
```

## 9. PDF-Export

```python
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
import io

def generate_pdf(data, title="Report"):
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4,
                           leftMargin=15*mm, rightMargin=15*mm,
                           topMargin=15*mm, bottomMargin=15*mm)

    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(title, styles['Heading1']))
    elements.append(Spacer(1, 10*mm))

    # Table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(table)

    doc.build(elements)
    output.seek(0)
    return output
```

## 10. ZIP-Bundle

```python
import zipfile
import io

def create_zip_bundle(files):
    """
    files = [
        {'name': 'report.xlsx', 'content': bytes_or_bytesio},
        {'name': 'folder/file.pdf', 'path': '/path/to/file.pdf'},
    ]
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            if 'content' in file:
                content = file['content']
                if hasattr(content, 'getvalue'):
                    content = content.getvalue()
                zf.writestr(file['name'], content)
            elif 'path' in file:
                zf.write(file['path'], file['name'])

    zip_buffer.seek(0)
    return zip_buffer
```

## 11. File Upload Handler

```python
from werkzeug.utils import secure_filename
import os

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'csv'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No filename'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    filename = secure_filename(file.filename)
    content = file.read()
    file_hash = get_file_hash(content)

    # Process file...

    return jsonify({'success': True, 'hash': file_hash})
```

## 12. Frontend: Fetch API Pattern

```javascript
// GET Request
async function loadData() {
    const response = await fetch('/api/data');
    const data = await response.json();
    return data;
}

// POST Request mit JSON
async function saveData(data) {
    const response = await fetch('/api/data', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    return response.json();
}

// File Upload
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData
    });
    return response.json();
}

// Download als Datei
async function downloadExport(endpoint, filename) {
    const response = await fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    const blob = await response.blob();

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
}
```

## 13. Materialize UI Components

```html
<!-- Card -->
<div class="card">
    <div class="card-content">
        <span class="card-title">Titel</span>
        <p>Inhalt</p>
    </div>
    <div class="card-action">
        <a href="#">Action</a>
    </div>
</div>

<!-- Collapsible -->
<ul class="collapsible">
    <li>
        <div class="collapsible-header">
            <i class="material-icons">folder</i>
            Kategorie
            <span class="badge">5</span>
        </div>
        <div class="collapsible-body">
            <!-- Items -->
        </div>
    </li>
</ul>

<!-- Modal -->
<div id="modal1" class="modal">
    <div class="modal-content">
        <h4>Titel</h4>
        <p>Inhalt</p>
    </div>
    <div class="modal-footer">
        <a class="modal-close btn-flat">Abbrechen</a>
        <a class="btn" onclick="save()">Speichern</a>
    </div>
</div>

<!-- Toast Notification -->
<script>
M.toast({html: 'Gespeichert!', classes: 'rounded green'});
</script>
```
