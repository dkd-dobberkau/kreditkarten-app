# Eigenbeleg-Feature — Design

**Datum:** 2026-05-27
**Status:** Design abgenickt, bereit für Implementation-Plan

## Ziel

Eine Kreditkarten-Abrechnung soll auch dann auf `abgeschlossen` gehen können, wenn für eine offene Transaktion kein Originalbeleg beschaffbar ist (Beleg verloren, nicht ausgestellt, nicht erhalten). Statt die Transaktion zu `ignorieren` — was steuerlich nicht zulässig ist, weil die Ausgabe ja real war — wird ein **Eigenbeleg** (Ersatzbeleg gemäß § 158 AO) generiert. Dieser ist steuerlich anerkannt, wenn er die Pflichtangaben enthält.

**Konkreter Auslöser:** Die April-2026-Abrechnung hat eine Google-Cloud-Transaktion über 0,27 €, deren Originalbeleg (März-Rechnung) nicht beschaffbar war. Heute bliebe diese Abrechnung auf ewig im Status `offen`.

## Nicht-Ziele

- Keine globale "Belege fehlen"-Übersicht (eigenes Feature, separat).
- Kein Bulk-Workflow ("alle fehlenden Belege auf einmal als Eigenbeleg").
- Keine Begründungs-Historie / Vorschläge aus früheren Eigenbelegen.

## Datenmodell

Erweiterung der `belege`-Tabelle:

| Spalte | Typ | Bedeutung |
|--------|-----|-----------|
| `match_typ` | TEXT | bekommt zusätzlich Wert `'eigenbeleg'` (neben heute `'auto'`, `'manuell'`) |
| `begruendung` | TEXT NULL | gespeicherte Begründung (nur befüllt wenn `match_typ='eigenbeleg'`) |

Keine Änderung an `transaktionen`. Ein Eigenbeleg ist semantisch ein zugeordneter Beleg → die Transaktion bekommt Status `zugeordnet`. Damit greift die existierende Logik "Abrechnung = abgeschlossen wenn alle Transaktionen zugeordnet/ignoriert sind" automatisch.

### Migration

Additive Migration in `init_db()` per `ALTER TABLE belege ADD COLUMN begruendung TEXT` mit Try/Except für Idempotenz (Pattern, das im Projekt bereits existiert). `match_typ` ist freie TEXT-Spalte, kein Schema-Constraint zu ändern.

## PDF-Generierung

Verwendet die bereits im Projekt eingebundene ReportLab-Library (heute genutzt für Export-PDFs).

**Inhalt des Eigenbeleg-PDFs:**

```
EIGENBELEG / ERSATZBELEG
gemäß § 158 AO

Aussteller:
  dkd Internet Service GmbH
  Kaiserstraße 73
  60329 Frankfurt am Main

Angaben zur Ausgabe:
  Datum der Ausgabe:       <transaktion.datum>
  Zahlungsempfänger:       <transaktion.haendler>
  Beschreibung:            <transaktion.beschreibung>
  Betrag:                  <transaktion.betrag> <transaktion.waehrung>
  Kategorie:               <transaktion.kategorie>

Begründung für Eigenbeleg:
  <begruendung_text>

Datum der Belegerstellung: <heute>

Unterschrift: _______________________
              Olivier Dobberkau
```

**Aussteller-Daten:** Werden aus der `konten`-Tabelle bzw. einer neuen Konstante gezogen — heute kein Feld für Firmenanschrift vorhanden. Für v1 hartcodiert in einer Modul-Konstante in `eigenbeleg_generator.py`; spätere Auslagerung in `einstellungen`-Tabelle möglich (out of scope).

**Speicherort:**
```
belege/archiv/<Karten-Bezeichnung>/<Monat_Jahr>/eigenbeleg_<transaktion_id>.pdf
```

Damit landet der Eigenbeleg automatisch im normalen Export-ZIP.

**Dateiname-Konvention:** `eigenbeleg_<transaktion_id>.pdf` — eindeutig pro Transaktion, kein Konflikt mit hochgeladenen Belegen (die heute mit Originalnamen abgelegt werden).

**`file_hash`:** SHA-256 über den PDF-Bytes, wie bei hochgeladenen Belegen.

## Backend

### Neues Modul: `parsers/eigenbeleg_generator.py`

(Liegt bei den Parsern weil verwandt mit Beleg-Verarbeitung; alternativ ein eigenes `services/`-Verzeichnis denkbar — heute existiert keins, daher nicht aufmachen.)

```python
def generate_eigenbeleg_pdf(transaktion: dict, begruendung_text: str, output_path: str) -> bytes:
    """Generiert Eigenbeleg-PDF, schreibt es nach output_path, gibt PDF-Bytes zurück."""
```

### Neuer Endpoint

```
POST /api/transaktionen/<int:transaktion_id>/eigenbeleg
```

**Request Body:**
```json
{
  "begruendung_typ": "beleg_nicht_erhalten" | "beleg_verloren" | "kein_beleg" | "sonstiges",
  "begruendung_text": "Freitext (gleich dem Typ-Label bei den drei Vorgaben, beliebig bei 'sonstiges')"
}
```

**Validierung:**
- Transaktion existiert, sonst 404
- Transaktion hat Status `offen` ODER bereits einen Eigenbeleg (`match_typ='eigenbeleg'`), sonst 400 (`{"error": "Transaktion hat bereits einen Originalbeleg"}`). Damit ist Re-Submit zur Korrektur möglich.
- `begruendung_text` nicht leer / nicht nur Whitespace, sonst 400

**Ablauf:**
1. Transaktions-Daten laden inkl. zugehöriger Abrechnung (für Pfadbestimmung)
2. PDF generieren über `eigenbeleg_generator.generate_eigenbeleg_pdf(...)`
3. SHA-256 hashen
4. Pfad: `belege/archiv/<Konto-Bezeichnung-slug>/<Monat_Jahr>/eigenbeleg_<id>.pdf` — Verzeichnisse anlegen falls fehlend
5. PDF schreiben (idempotent: bei Re-Submit überschreiben — Eigenbeleg kann korrigiert werden)
6. `belege`-Row einfügen (oder bei Re-Submit updaten): `transaktion_id`, `datei_name`, `datei_pfad`, `file_hash`, `match_typ='eigenbeleg'`, `match_confidence=1.0`, `begruendung=<text>`, `extrahierte_daten=NULL`
7. `transaktionen.status = 'zugeordnet'`
8. Atomare Transaktion (alles oder nichts), mit `db_execute_with_retry()` wie im Projekt üblich

**Response:**
```json
{
  "success": true,
  "beleg_id": 254,
  "pdf_pfad": "belege/archiv/American_Express_Business_Card/April_2026/eigenbeleg_226.pdf"
}
```

**Re-Submit-Verhalten:** Wenn für eine Transaktion bereits ein Eigenbeleg existiert (also `belege` mit `match_typ='eigenbeleg'` und passender `transaktion_id`), wird das vorhandene PDF überschrieben und der DB-Eintrag aktualisiert. So kann der User Tippfehler in der Begründung korrigieren.

**Schutz gegen falsche Mischung:** Wenn die Transaktion bereits einen Originalbeleg hat (`belege`-Eintrag mit `match_typ != 'eigenbeleg'`), liefert der Endpoint 400 — der User soll erst den falschen Beleg lösen. Diese Prüfung ist Teil der Validierungs-Liste oben.

## Frontend

### Transaktions-Detail-Modal

Im existierenden Modal (siehe `index.html`, Suche nach `detail-status-select`) wird ein neuer Bereich eingefügt, sichtbar **nur wenn Transaktions-Status = `offen`**:

```
─────────────────────────────────────
Kein Originalbeleg vorhanden?
[Eigenbeleg erstellen ▾]
─────────────────────────────────────
```

Klick auf den Button entfaltet (oder öffnet als kleines Sub-Panel im selben Modal):

```
Begründung:
  ○ Beleg nicht erhalten
  ○ Beleg verloren
  ○ Kein Beleg ausgestellt
  ○ Sonstiges:  [Freitext-Feld ____________]

[Eigenbeleg erstellen]   [Abbrechen]
```

Bei Auswahl eines der ersten drei Radio-Buttons wird `begruendung_text` automatisch auf das Label gesetzt (z.B. `"Beleg nicht erhalten"`). Bei `Sonstiges` wird der Freitext-Feld-Wert genommen; das Feld ist nur dann aktiv und Pflicht.

**Submit:**
- POST `/api/transaktionen/<id>/eigenbeleg` mit dem Body
- Erfolg: Toast "Eigenbeleg erstellt", Modal schließen, Transaktionsliste neu laden
- Fehler: Toast mit Fehlermeldung

### Visuelle Differenzierung in der Transaktionsliste

In `renderTransaktionen()`: Wenn der zugeordnete Beleg ein Eigenbeleg ist (`t.beleg_match_typ === 'eigenbeleg'`), wird statt des `attachment`-Icons ein `description`-Icon angezeigt (mit Tooltip "Eigenbeleg"). Das macht auf einen Blick erkennbar, ob ein Originalbeleg oder ein Ersatz vorliegt.

**Voraussetzung:** Die Transaktions-API muss `match_typ` und `begruendung` mitliefern. Heute liefert sie `beleg_datei`; ergänzen um `beleg_match_typ` und `beleg_begruendung`.

### Export-Liste (Excel)

Im Excel-Export bekommen Eigenbelege eine zusätzliche Spalte/Markierung "Eigenbeleg" und die Begründung in einer Spalte "Bemerkung". Falls der Excel-Export keine Bemerkung-Spalte hat, wird sie hinzugefügt.

*(Out of scope für v1 falls Komplexität sprengt — dann nur PDF-Eigenbeleg, Excel unverändert. Wird im Implementation-Plan entschieden.)*

## Tests

- **Unit:** `eigenbeleg_generator.generate_eigenbeleg_pdf()` erzeugt PDF mit allen Pflichtfeldern (PDF-Text extrahieren, auf Substrings prüfen).
- **Integration:** Endpoint POST mit gültigem Payload → Beleg-Row angelegt, Transaktions-Status auf `zugeordnet`, PDF existiert auf Platte.
- **Validation:** Leere Begründung → 400. Nicht-existente Transaktion → 404. Bereits zugeordnete Transaktion mit Originalbeleg → 400.
- **Idempotenz:** Zweiter POST für dieselbe Transaktion mit anderer Begründung → PDF und DB-Eintrag aktualisiert, kein Duplikat.

## Offene Punkte (für Implementation-Plan)

- Genaue Liste der Aussteller-Daten (heute keine Firmen-Stammdaten in der DB — wird in v1 als Konstante hartcodiert, mit TODO-Kommentar für spätere Einstellungs-Auslagerung).
- Excel-Export-Anpassung: in v1 enthalten oder out-of-scope?
- Konto-Bezeichnung-Slug-Funktion: existiert sie im Projekt schon (für die Archiv-Pfade)? Wenn nicht, muss eine kleine Helper-Funktion her.
