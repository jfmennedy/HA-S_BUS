# Changelog

Alle bemerkenswerten Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
und dieses Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Geplant
- Automatische Erkennung aller verfügbaren Datenpunkte
- Unterstützung für Timer und Counter Entitäten
- Diagnostics Support

## [0.6.0] - 2026-11-05

### Hinzugefügt
- **Ganze Anlagenteile übernehmen:** Bei „Datenpunkte aus Projekt wählen“
  lassen sich Anlagenteile wie „S01 Zirk. UWP“ mit allen Datenpunkten auf
  einmal auswählen. Ein Anlagenteil umfasst alle FBoxen mit derselben
  Beschreibung (z. B. Pumpe und Störmeldungen) und die zugehörigen internen
  Symbole.
- Jeder Anlagenteil wird ein eigenes Gerät (verbunden über die PCD). Auf der
  Geräteseite legt „Zum Dashboard hinzufügen“ eine Karte mit allen
  Datenpunkten an. Entitäten heißen dort wie in der DDC Suite („Betrieb“),
  die Beschreibung steht als Attribut `description` bereit.
- Bereits gewählte Datenpunkte aus dem Projekt wandern automatisch in ihr
  Anlagenteil-Gerät; eigene Namen bleiben erhalten. Ein erneuter Import ist
  nicht nötig. Leere Anlagenteil-Geräte werden entfernt.

## [0.5.0] - 2026-11-05

### Hinzugefügt
- **PG5-Projekt importieren:** Fupla-Datei (`.fup`) und Linker-Map (`.map`)
  hochladen, dann Datenpunkte je Anlage aus einer Liste mit Klartext-Namen
  und Beschreibungen der DDC-Suite-FBoxen wählen. Faktor, Einheit (°C, %)
  und Wertebereich kommen aus dem Projekt. Standardmäßig werden
  Betriebswerte (Stufen 1–3) angeboten, auf Wunsch auch Parameter.
- Bei erneutem Import nach einem Programmumbau werden gewählte Datenpunkte
  über ihren Symbolnamen auf neue Adressen umgestellt; Entitäten bleiben
  erhalten.
- **Zahlenfelder:** Beschreibbare Register werden als einstellbare Number-
  Entitäten angelegt (aus dem Projekt oder über „Register hinzufügen“ mit
  „Beschreibbar“).
- Entitäten aus dem Projekt tragen das PG5-Symbol als Attribut.

## [0.4.8] - 2026-11-05

### Geändert
- Modell und Firmware werden lesbar angezeigt: aus „D3M53“ wird „PCD3.M53“
  (CPU-Familie PCD3.M53xx), aus „128“ wird „1.28“. Die PCD liefert nur
  Haupt- und Nebenversion, keine Patch-Stelle.

## [0.4.7] - 2026-11-05

### Behoben
- Firmware und PCD-Typ werden jetzt mit dem S-Bus-Befehl „Read Program
  Version“ gelesen. Bisher wurden die Register R 600–612 als
  „Systemregister“ ausgelesen; bei einer PCD sind das aber normale
  Programmregister, daher zeigten die Geräteinformationen Werte wie
  „Firmware: 0“ oder eine falsche Seriennummer.
- Die angezeigte Seriennummer entfällt, weil S-Bus keine dokumentierte
  Abfrage dafür bietet. Gerätekennung ist IP-Adresse, Port und Station;
  bestehende Geräte und Entitäten werden automatisch übernommen.

## [0.4.6] - 2026-11-05

### Geändert
- README, Badges und Links in der Integration (Dokumentation, Fehlermeldungen
  melden) zeigen auf dieses Repository statt auf das nicht mehr gepflegte
  Original. Fork-Hinweis und Umstiegsanleitung für HACS ergänzt.
- Systemregister-Tabelle im README korrigiert.

## [0.4.5] - 2026-11-05

### Behoben
- Seit 0.4.2 wurden Antworten verworfen, wenn Version oder Typ im
  Ether-S-Bus-Header von den gesendeten Werten abwichen. Echte PCDs tun das
  zum Teil, dann ließ sich die PCD nicht mehr einrichten
  („Einrichtungsfehler, wird erneut versucht“). Diese Felder werden nicht mehr
  zur Prüfung verwendet; Länge, CRC und Sequenznummer reichen aus.
- Die Meldung beim Einrichtungsfehler enthält jetzt die Ursache.

## [0.4.4] - 2026-11-05

Enthält die unten für 0.4.3 beschriebenen Änderungen. Das Release v0.4.3
wurde versehentlich vor dem Merge angelegt und enthält den Stand von 0.4.2.

## [0.4.3] - 2026-11-05

### Behoben
- PCDs, die auf die Seriennummer-Register (R 611/612) oder andere optionale
  Systemregister gar nicht antworten, ließen sich mit 0.4.2 nicht mehr
  einrichten („wird nicht mehr von der sbus-Integration bereitgestellt“).
  Fehlt eine Antwort, wird jetzt mit R 600 geprüft, ob die PCD erreichbar ist;
  das Register gilt dann als nicht vorhanden.
- Ändert sich die Gerätekennung (z. B. vom bisherigen Platzhalter „UNKNOWN“
  auf IP/Port/Station), werden Gerät und Entitäten übernommen statt neu
  angelegt. Entitäts-IDs, Namen, Bereiche und Verlauf bleiben erhalten.

### Geändert
- `pyserial-asyncio` durch `serialx` ersetzt, wie von Home Assistant
  gefordert (die alte Bibliothek funktioniert ab Home Assistant 2027.2 nicht
  mehr). Behebt die Warnung beim Start.
- Ist die PCD nicht erreichbar, erscheint nur noch ein Eintrag im Log beim
  Ausfall und einer bei der Erholung, statt einer Fehlermeldung pro
  Abfragezyklus.

## [0.4.2] - 2026-11-04

### Behoben
- Ether-S-Bus-Frames mit falscher Version oder falschem Protokolltyp werden
  verworfen.
- TCP: Beschädigte Frames werden übersprungen statt die Anfrage abzubrechen;
  bei ungültiger Längenangabe wird die Verbindung neu aufgebaut.
- Profi-S-Bus: Gateway-Antworten werden vollständig gelesen, und Antworten
  mit fremder Sequenznummer werden verworfen.
- Ein Timeout beim Lesen der Geräteinformationen bricht die Einrichtung ab,
  statt die PCD mit unvollständigen Daten anzulegen.
- Liefert die PCD keine Seriennummer, wird der Endpunkt (Adresse, Port,
  Station) als Kennung verwendet, damit mehrere solcher PCDs angelegt werden
  können.
- Flags, die über mehrere Telegramme gelesen werden, bilden einen
  konsistenten Zustand (kein Schreibbefehl dazwischen).
- Eine abgelehnte oder nicht erreichbare Verbindung meldet „Verbindung
  fehlgeschlagen“ statt „Unerwarteter Fehler“, bei TCP mit Hinweis auf UDP.
  Der Verbindungsaufbau hat ein Zeitlimit.

## [0.4.1] - 2026-11-04

### Hinzugefügt
- Icon und Logo von Saia Burgess Controls im Ordner `brand/`
  (wird ab Home Assistant 2026.3 angezeigt).

## [0.4.0] - 2026-11-04

### Hinzugefügt
- Register und Flags sind in den Optionen der Integration konfigurierbar
  (hinzufügen, bearbeiten, entfernen). Register werden zu Sensoren mit Name,
  Datentyp (Ganzzahl mit/ohne Vorzeichen, Gleitkomma), Faktor und Einheit;
  die Einheit setzt automatisch den Sensortyp (z. B. °C → Temperatur).
  Flags werden zu Binärsensoren oder, wenn beschreibbar, zu Schaltern.
- Deutsche und englische Übersetzungen der Oberfläche.

### Geändert
- Nur noch konfigurierte Adressen werden abgefragt; benachbarte Adressen
  werden in einem Telegramm gelesen.
- Ohne Konfiguration bleiben die bisherigen Entitäten (R 0–9, F 0–31,
  Schalter F 0–7) erhalten. Sobald Datenpunkte konfiguriert sind, werden
  nicht mehr benötigte Entitäten automatisch entfernt.
- Kein unnötiger Reconnect (mit 5 s Wartezeit) mehr beim Start.

## [0.3.2] - 2026-11-04

### Geändert
- Die Aktionen `sbus.read_register` und `sbus.read_flag` geben die gelesenen
  Werte jetzt als Antwort zurück (in den Entwicklerwerkzeugen unter
  „Aktionen“ sichtbar). Register werden als Rohwert, vorzeichenbehaftet,
  hexadezimal und als IEEE-Float ausgegeben.
- Fehler beim Lesen oder Schreiben werden als Fehlermeldung angezeigt statt
  nur ins Log geschrieben.

### Behoben
- Adressen und Anzahl aus der Oberfläche (Fließkommazahlen) führten zu einem
  Fehler beim Erstellen des Telegramms.
- Aktionen berücksichtigen jetzt das ausgewählte Gerät.

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

[Unreleased]: https://github.com/jfmennedy/HA-S_BUS/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.6.0
[0.5.0]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.5.0
[0.4.8]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.8
[0.4.7]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.7
[0.4.6]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.6
[0.4.5]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.5
[0.4.4]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.4
[0.4.2]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.2
[0.4.1]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.1
[0.4.0]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.4.0
[0.3.2]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.3.2
[0.3.1]: https://github.com/jfmennedy/HA-S_BUS/releases/tag/v0.3.1
[0.1.0]: https://github.com/MrTir1995/HA-S_BUS/releases/tag/v0.1.0
