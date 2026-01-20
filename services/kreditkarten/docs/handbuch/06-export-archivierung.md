# Export & Archivierung

## Abrechnung exportieren

Wenn alle Transaktionen Belege haben, kannst du die Abrechnung exportieren:

1. Wähle die Abrechnung aus
2. Klicke auf **Export**
3. Ein ZIP-Archiv wird heruntergeladen

### Inhalt des ZIP-Archivs

```
American_Express_Business_Card_Januar_2026.zip
├── Abrechnung_Januar_2026.xlsx    # Excel-Übersicht
├── Belege/
│   ├── 01_Amazon_49.99.pdf
│   ├── 02_Deutsche_Bahn_89.00.pdf
│   └── ...
└── Bewirtungsbelege/
    └── 03_Restaurant_XY.pdf
```

### Excel-Datei enthält
- Alle Transaktionen mit Datum, Händler, Betrag, Kategorie
- Verweis auf zugeordneten Beleg
- Summen nach Kategorie

## Automatische Archivierung

Nach dem Export werden alle Belege automatisch archiviert:

**Vorher:** `belege/inbox/Rechnung.pdf`
**Nachher:** `belege/archiv/American_Express/Januar_2026/Rechnung.pdf`

### Archiv-Struktur
```
belege/archiv/
├── American_Express_Business_Card/
│   ├── November_2025/
│   ├── Dezember_2025/
│   └── Januar_2026/
└── Mastercard_dkd/
    ├── November_2025/
    └── Dezember_2025/
```

## Manuell archivieren

Du kannst auch ohne Export archivieren:
1. Wähle die Abrechnung
2. Klicke auf **Archivieren**
3. Alle Belege werden ins Archiv verschoben

## Tipps

- **Export erst wenn komplett**: Alle Transaktionen sollten Belege haben
- **Archiv nicht löschen**: Die App braucht Zugriff auf archivierte Belege
- **Backup**: Das Archiv regelmäßig sichern
