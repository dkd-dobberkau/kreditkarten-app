# Design: Benutzerhandbuch

**Datum:** 2026-01-20
**Status:** Genehmigt

## Ziel

Vollständiges Benutzerhandbuch für Kollegen, zugänglich in der App und als PDF.

## Zugangswege

### 1. In-App Hilfe
- Hilfe-Button (`?`) in der Navigationsleiste
- Öffnet Vollbild-Modal mit Seitennavigation
- Kontextsensitiv: Je nach Bereich springt es zum passenden Kapitel

### 2. PDF-Export
- Button im Hilfe-Modal: "Als PDF herunterladen"
- Generiert komplettes Handbuch als druckbares PDF

## Technische Umsetzung

### Dateien
```
docs/handbuch/
├── 01-erste-schritte.md
├── 02-import.md
├── 03-belege-zuordnen.md
├── 04-kategorisierung.md
├── 05-bewirtungsbelege.md
├── 06-export-archivierung.md
└── 07-konten-verwalten.md
```

### Backend
- Neue Route `GET /hilfe` – rendert Handbuch-Modal
- Neue Route `GET /hilfe/<kapitel>` – liefert einzelnes Kapitel als HTML
- Neue Route `GET /hilfe/pdf` – generiert PDF mit ReportLab

### Frontend
- Hilfe-Button in Navigation
- Modal mit linker Kapitel-Navigation und rechtem Inhaltsbereich
- PDF-Download-Button

## UI-Layout

```
┌─────────────────────────────────────────────────┐
│  Benutzerhandbuch                    [PDF] [X]  │
├──────────────┬──────────────────────────────────┤
│              │                                  │
│ 1. Erste     │  Inhalt des gewählten Kapitels   │
│    Schritte  │                                  │
│ 2. Import    │  Mit Screenshots und             │
│ 3. Belege    │  Schritt-für-Schritt             │
│ 4. Kategor.  │  Anleitungen                     │
│ 5. Bewirtung │                                  │
│ 6. Export    │                                  │
│ 7. Konten    │                                  │
│              │                                  │
└──────────────┴──────────────────────────────────┘
```

## Kapitelinhalte

### 1. Erste Schritte
- Was macht die App? (Kreditkartenabrechnungen mit Belegen abgleichen)
- Übersicht der Benutzeroberfläche
- Typischer Workflow: Import → Zuordnen → Export

### 2. Abrechnungen importieren
- CSV-Datei von der Bank herunterladen
- PDF-Abrechnungen importieren
- Konto auswählen, Periode wird vorgeschlagen
- Drag & Drop oder Datei-Auswahl

### 3. Belege zuordnen
- Belege hochladen (Inbox)
- Automatisches Matching verstehen (Betrag, Datum, Händler)
- Manuelles Zuordnen per Drag & Drop
- Beleg-Details bearbeiten

### 4. Kategorisierung
- Automatische Kategorisierung durch KI
- Kategorien manuell ändern
- Kategorie-Regeln für wiederkehrende Händler

### 5. Bewirtungsbelege
- Wann brauche ich einen Bewirtungsbeleg?
- Formular ausfüllen (Anlass, Teilnehmer, Unterschrift)
- Bewirtungsbeleg-PDF generieren

### 6. Export & Archivierung
- Abrechnung als ZIP exportieren (Excel + Belege)
- Automatische Archivierung nach Export
- Ordnerstruktur im Archiv

### 7. Konten verwalten
- Neues Konto anlegen
- Bank-Format einstellen (Amex, Visa DKB, etc.)

## Kontextsensitive Hilfe

| Bereich in der App | Öffnet Kapitel |
|--------------------|----------------|
| Import-Modal | 2. Abrechnungen importieren |
| Transaktionsliste | 3. Belege zuordnen |
| Beleg-Upload | 3. Belege zuordnen |
| Bewirtungsbeleg-Modal | 5. Bewirtungsbelege |
| Export-Bereich | 6. Export & Archivierung |
| Konto-Modal | 7. Konten verwalten |

## Implementierungsschritte

1. Markdown-Dateien für alle Kapitel erstellen
2. Backend-Routen implementieren (`/hilfe`, `/hilfe/<kapitel>`, `/hilfe/pdf`)
3. Hilfe-Modal in Frontend einbauen
4. Hilfe-Buttons an relevanten Stellen platzieren
5. PDF-Generierung implementieren
6. Testen und Docker-Rebuild
