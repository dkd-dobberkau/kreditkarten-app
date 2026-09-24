# Backlog - Kreditkarten-Abgleich

## Hohe Priorität

- [ ] **VCF-Import für Personen** - Kontakte aus vCard-Dateien importieren (wie in spesen-app)
- [ ] **Bewirtungsbeleg bearbeiten** - Bestehende Belege nachträglich ändern/löschen
- [ ] **Transaktions-Suche** - Volltextsuche über alle Transaktionen
- [ ] **Backup/Restore** - Datenbank-Export/Import für Datensicherung
- [ ] **Auto-Match: Betrag als Mindestkriterium** - Datum (0,3) + Händler (0,2) erreichen die Schwelle von 0,5, auch wenn der Betrag nicht passt. September 2026: eine BMW-Charging-Rechnung über 10,98 € wurde zweimal automatisch einer Buchung über 29,38 € zugeordnet. Zuordnen nur bei übereinstimmendem Betrag oder erklärbarer Fremdwährungsabweichung.
- [ ] **Sammelrechnungen: Betrag der Einzelrechnung extrahieren** - Bei mehrseitigen PDFs mit vorangestellter Rechnungsübersicht liest die Extraktion die Gesamtsumme statt des Einzelbetrags (BMW Charging 08/2026: 108,33 € statt 78,95 € bzw. 29,38 €) und nimmt die Zahlungsreferenz als Rechnungsnummer.

## Mittlere Priorität

- [ ] **Dashboard-Statistiken** - Ausgaben nach Kategorie, Monat, Jahr visualisieren
- [ ] **Wiederkehrende Händler** - Automatische Kategorisierung basierend auf bekannten Händlern
- [ ] **Beleg-Vorschau im Modal** - PDF direkt im Zuordnungs-Dialog anzeigen
- [ ] **Multi-Beleg pro Transaktion** - Mehrere Belege einer Transaktion zuordnen
- [ ] **Kommentar-Feld** - Notizen zu einzelnen Transaktionen

## Nice-to-Have

- [ ] **Dark Mode** - Dunkles Theme
- [ ] **Tastenkürzel** - Keyboard-Navigation (j/k, Enter, etc.)
- [ ] **Drag & Drop Belege** - Belege direkt auf Transaktionen ziehen
- [ ] **E-Mail-Versand** - PDF-Report per E-Mail senden
- [ ] **Mehrere Kreditkarten** - Konsolidierte Ansicht über alle Karten
- [ ] **OCR-Verbesserung** - Bessere Beleg-Erkennung mit Claude Vision

## Technisch

- [ ] **Unit Tests** - pytest für Backend-Funktionen
- [ ] **API-Dokumentation** - OpenAPI/Swagger Spec
- [ ] **Rate Limiting** - Schutz vor API-Missbrauch
- [ ] **Audit-Log** - Änderungshistorie nachverfolgen
