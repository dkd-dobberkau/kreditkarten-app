"""
Zentrale Konfiguration für die Kreditkarten-App.

Hält gemeinsame Einstellungen, die an mehreren Stellen gebraucht werden,
damit ein Wechsel (z.B. des Claude-Modells) nur an einer Stelle erfolgt.
"""

import os

# Claude-Modell für AI-Kategorisierung und Beleg-/PDF-Extraktion.
# Überschreibbar via Umgebungsvariable ANTHROPIC_MODEL (siehe .env).
ANTHROPIC_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20250929')
