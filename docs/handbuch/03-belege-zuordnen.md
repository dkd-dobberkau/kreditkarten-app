# Belege zuordnen

## Belege hochladen

1. Scrolle zum Bereich **Belege** unterhalb der Transaktionsliste
2. Ziehe PDF- oder Bilddateien in den Upload-Bereich
3. Oder klicke zum Auswählen mehrerer Dateien

### Unterstützte Formate
- PDF (empfohlen)
- JPG, PNG (Fotos von Belegen)

## Automatisches Matching

Die App versucht, hochgeladene Belege automatisch zuzuordnen:

| Kriterium | Gewichtung |
|-----------|------------|
| Betrag stimmt exakt | 50% |
| Datum passt (±7 Tage) | 30% |
| Händlername ähnlich | 20% |

Belege mit **Konfidenz über 50%** werden automatisch zugeordnet.

### Matching-Status
- **Grün**: Automatisch zugeordnet, hohe Konfidenz
- **Gelb**: Zugeordnet, aber bitte prüfen
- **Rot**: Kein passender Beleg gefunden

## Manuelles Zuordnen

Falls die automatische Zuordnung nicht passt:

1. Finde den Beleg in der Beleg-Liste
2. Ziehe ihn per **Drag & Drop** auf die richtige Transaktion
3. Der Beleg wird sofort zugeordnet

### Zuordnung aufheben
- Klicke auf das **X** neben dem Beleg in der Transaktion
- Der Beleg wandert zurück in die Inbox

## Beleg-Details bearbeiten

Klicke auf einen zugeordneten Beleg um die Details zu sehen:
- Extrahierter Betrag
- Extrahiertes Datum
- Erkannter Händler

Du kannst diese Werte manuell korrigieren falls die automatische Erkennung falsch lag.

## Tipps

- **Dateinamen** helfen beim Matching: `2026-01-15_Amazon_49.99.pdf` wird besser erkannt
- **Mehrere Belege** für eine Transaktion sind möglich (z.B. Rechnung + Lieferschein)
- Belege ohne Zuordnung bleiben in der **Inbox** für spätere Verwendung
