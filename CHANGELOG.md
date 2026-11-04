# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Geplant
- YAML-Konfiguration für Entitäten
- Automatische Erkennung aller verfügbaren Datenpunkte
- Unterstützung für Timer und Counter Entitäten
- Diagnostics Support

## [0.3.1] - 2026-11-04

### Behoben
- Ether-S-Bus: Telegramme enthalten jetzt den vorgeschriebenen 8-Byte-Header
  (Länge, Version, Typ, Sequenznummer), und die CRC wird über den gesamten Frame
  berechnet. Bisher hat die PCD jede Anfrage verworfen, was sich als
  "Timeout communicating with S-Bus device" gezeigt hat.
- Korrekter PDU-Aufbau für Register- und Flag-Befehle (`Anzahl-1` als 1 Byte
  vor der Adresse, Byte-Zähler bei Schreibbefehlen).
- Antworten werden am richtigen Offset ausgewertet; Schreibbefehle prüfen ACK/NAK.
- UDP-Antworten werden über die Sequenznummer zugeordnet; veraltete oder
  beschädigte Antworten werden verworfen.
- Serial-S-Bus nutzt Data-Mode-Framing (0xB5, Byte-Stuffing, 8N1).
- Setup und Config-Flow schlagen fehl, wenn die PCD nicht antwortet, statt ein
  Gerät "SAIA PCD (Unknown)" anzulegen.

## [0.3.0] - 2026-01-19

### Hinzugefügt
- **Multi-Protokoll Support**:
  - Ether-S-Bus (UDP/TCP)
  - Serial-S-Bus (RS-232/RS-485 über USB oder TCP-Seriell-Bridge)
  - Profi-S-Bus (Profibus FDL Gateway)
- **Auto-Discovery**:
  - mDNS/Zeroconf Discovery (`_http._tcp.local.`, `_sbus._tcp.local.`)
  - SSDP Discovery für SAIA-Geräte
  - Automatischer Bestätigungsdialog mit vorausgefüllten Daten
- **Connection Health Monitoring**:
  - Automatische Wiederverbindung nach Verbindungsabbruch
  - Tracking von aufeinanderfolgenden Fehlern
  - Reconnect-Delay mit exponential backoff
  - Graceful Shutdown beim Entladen der Integration
- **Retry-Logik**:
  - 3 Versuche bei Netzwerkfehlern
  - Exponential Backoff (0.5s, 1s, 2s)
  - Sequenznummern-Management für Ether-S-Bus
- **Enhanced Device Info**:
  - Formatierte Versionsstrings (Major.Minor.Patch)
  - Erweiterte Fehlerbehandlung beim Auslesen
  - Hardware-Version und Protokoll-Version

### Behoben
- **CRC-16 Berechnung**: Initialwert von 0xFFFF auf 0x0000 korrigiert (gemäß S-Bus Spezifikation)
- Verbesserte Verbindungsstabilität durch Retry-Mechanismus
- Device Info Parsing-Fehler behoben

### Geändert
- Config Flow jetzt mit Multi-Step für Protokollauswahl
- Coordinator nutzt jetzt Health Monitoring
- Verbesserte Logging-Ausgaben mit Fehler-Counter
- `async_unload_entry` nutzt jetzt `coordinator.async_shutdown()`

### Technische Details
- Basis-Klasse `SBusProtocolBase` für alle Protokoll-Varianten
- Factory Pattern in `sbus_protocol.py` für dynamische Instanziierung
- pyserial-asyncio 0.6 Abhängigkeit für Serial-Support
- Unterstützung für Baudraten 1200-115200
- TCP-Seriell-Bridge Support (ser2net)

## [0.1.0] - 2026-01-19

### Hinzugefügt
- Initiale Release der S-Bus Integration
- Ether-S-Bus Support (UDP Port 5050)
- UI-basierte Konfiguration (Config Flow)
- Sensor-Entitäten für Register
- Binary Sensor-Entitäten für Flags
- Switch-Entitäten für schreibbare Flags
- DataUpdateCoordinator für zentrale Datenverwaltung
- CRC-16-CCITT Validierung
- Services:
  - `sbus.read_register` - Register lesen
  - `sbus.write_register` - Register schreiben
  - `sbus.read_flag` - Flags lesen
  - `sbus.write_flag` - Flag schreiben
- Automatische Device-Identifikation über Systemregister
- Device Registry Integration
- Reconfigure Flow für Änderung von Verbindungseinstellungen
- Options Flow für Scan-Intervall Anpassung
- Vollständige Async/Await Implementierung
- Dev Container für VS Code
- GitHub Actions CI/CD
- Unit Tests mit pytest
- Linting mit Ruff
- Pre-commit Hooks
- Umfassende Dokumentation

### Technische Details
- Python 3.13 Support
- Home Assistant 2024.1.0+
- Nicht-blockierende UDP-Kommunikation
- Type Hints für alle Funktionen
- Logging und Error Handling

[Unreleased]: https://github.com/MrTir1995/HA-S_BUS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MrTir1995/HA-S_BUS/releases/tag/v0.1.0
