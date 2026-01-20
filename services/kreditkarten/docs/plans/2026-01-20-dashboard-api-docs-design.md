# Design: Dashboard & API-Dokumentation

**Datum:** 2026-01-20
**Status:** Genehmigt

## Übersicht

Zwei Features parallel:
1. **Dashboard** - Statistiken mit Chart.js (Kategorien, Verlauf, Top-Händler)
2. **API-Dokumentation** - Swagger UI mit Flask-RESTX

## 1. Dashboard

### Navigation
Neuer Menüpunkt "Dashboard" zwischen "Konten" und "Abrechnungen".

### Layout
```
┌─────────────────────────────────────────────────────┐
│  Filter: [Konto ▼] [Jahr ▼] [Zeitraum: 12 Monate ▼] │
├─────────────────────┬───────────────────────────────┤
│  Ausgaben nach      │  Monatlicher Verlauf          │
│  Kategorie          │  (Liniendiagramm)             │
│  (Tortendiagramm)   │                               │
├─────────────────────┴───────────────────────────────┤
│  Top 10 Händler (Balkendiagramm, horizontal)        │
└─────────────────────────────────────────────────────┘
```

### Filter
- Konto: Alle / einzelne Kreditkarte
- Jahr: 2025, 2026, etc.
- Zeitraum: Letzte 3/6/12 Monate oder ganzes Jahr

### Technologie
- **Chart.js** für Diagramme (leichtgewichtig, kein Build nötig)

## 2. Mini-Statistiken in Abrechnungs-Detailseite

Position oberhalb der Transaktionsliste:

```
┌──────────────┬──────────────┬───────────────────────┐
│ Kategorien   │ Top Händler  │ Status               │
│ Reise: 45%   │ Motel One    │ ✓ 12/15 mit Beleg    │
│ Bewirt: 30%  │ DB Bahn      │ ⚠ 3 ohne Beleg       │
│ Sonst: 25%   │ Tank-Stelle  │                      │
└──────────────┴──────────────┴───────────────────────┘
```

Berechnung im Frontend aus bereits geladenen Transaktionen.

## 3. API-Dokumentation

### Zugang
- URL: `/api/docs`
- Optional: Menüpunkt "API"

### Technologie
- **Flask-RESTX** für automatische Swagger UI
- Namespaces für Gruppierung

### Namespaces
- `/api/konten` - Konten-Verwaltung
- `/api/abrechnungen` - Abrechnungen
- `/api/transaktionen` - Transaktionen
- `/api/belege` - Belege
- `/api/statistiken` - Dashboard-Daten (neu)
- `/api/kategorien` - Kategorien
- `/api/hilfe` - Hilfe/Handbuch

## 4. Statistik-API

### Endpunkt
`GET /api/statistiken`

### Parameter
| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| konto_id | int | Filter auf ein Konto (optional) |
| jahr | int | z.B. 2026 (optional) |
| monate | int | Anzahl Monate zurück, default: 12 |

### Response
```json
{
  "zeitraum": {
    "von": "2025-02-01",
    "bis": "2026-01-31"
  },
  "kategorien": [
    {"name": "reisekosten", "label": "Reisekosten", "summe": 4500.00, "anzahl": 23}
  ],
  "monatlich": [
    {"monat": "2025-02", "summe": 1200.00}
  ],
  "haendler": [
    {"name": "MOTEL ONE", "summe": 1800.00, "anzahl": 12}
  ]
}
```

## 5. Implementierung

### Neue Dateien
- `static/js/chart.min.js` - Chart.js Library

### Änderungen
- `app.py` - Flask-RESTX Integration, Statistik-Endpunkt
- `templates/index.html` - Dashboard-Sektion, Mini-Stats
- `requirements.txt` - flask-restx

### Abhängigkeiten
```
flask-restx>=1.3.0
```
