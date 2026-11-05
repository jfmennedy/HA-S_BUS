# SAIA S-Bus Integration for Home Assistant

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)
[![hacs][hacsbadge]][hacs]

![Project Maintenance][maintenance-shield]

**Diese Integration ermöglicht die Kommunikation mit SAIA PCD Steuerungen über das S-Bus Protokoll in Home Assistant.**

> [!NOTE]
> Dies ist ein gepflegter Fork von [MrTir1995/HA-S_BUS](https://github.com/MrTir1995/HA-S_BUS),
> das seit Längerem nicht mehr aktualisiert wird. Gegenüber dem Original
> funktioniert hier die Ether-S-Bus-Kommunikation mit echten PCDs (im Original
> endet die Einrichtung mit „Timeout communicating with S-Bus device“), und
> Register und Flags sind direkt in Home Assistant konfigurierbar.
> Alle Änderungen stehen im [CHANGELOG](CHANGELOG.md).

## 🌟 Features

- **Multi-Protokoll Support**: 
  - **Ether-S-Bus**: UDP/TCP über Ethernet (Port 5050)
  - **Serial-S-Bus**: RS-232/RS-485 über USB oder TCP-Seriell-Bridge
  - **Profi-S-Bus**: Profibus FDL Gateway-Unterstützung
- **Auto-Discovery**: Automatische Erkennung über mDNS/Zeroconf und SSDP
- **Connection Health Monitoring**: Automatische Wiederverbindung bei Verbindungsabbrüchen
- **Umfassende Datenpunkte**: Register, Flags, Timer, Counter, Data Blocks
- **CRC-16 Validierung**: Sichere Datenübertragung gemäß S-Bus Spezifikation
- **Retry-Logik**: Exponential Backoff bei Netzwerkfehlern
- **Native Integration**: Nahtlose Integration in die Home Assistant UI
- **Async/Await**: Moderne asynchrone Implementierung für beste Performance

## 📋 Unterstützte Geräte

Diese Integration unterstützt SAIA PCD Steuerungen mit S-Bus Schnittstelle, einschließlich:

- PCD1.M2120, PCD1.M2160
- PCD2.M480, PCD2.M5540
- PCD3.M5560, PCD3.M6860
- E-Line Serie (PCD1.E1000, etc.)
- Und weitere PCD-Modelle mit S-Bus Support

## 🚀 Installation

### HACS (Empfohlen)

[![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jfmennedy&repository=HA-S_BUS&category=integration)

Oder manuell:

1. Öffnen Sie HACS in Home Assistant
2. Klicken Sie auf "Integrations"
3. Klicken Sie auf das Menü (⋮) in der oberen rechten Ecke
4. Wählen Sie "Custom repositories"
5. Fügen Sie die Repository-URL hinzu: `https://github.com/jfmennedy/HA-S_BUS`
6. Wählen Sie die Kategorie "Integration"
7. Klicken Sie auf "ADD"
8. Suchen Sie nach "SAIA S-Bus"
9. Klicken Sie auf "Download"

**Umstieg vom Original-Repository:** In HACS das Repository von MrTir1995
entfernen, dieses Repository wie oben hinzufügen, die Integration
herunterladen und Home Assistant neu starten. Weil beide Varianten dieselbe
Integration (`sbus`) sind, bleibt eine bestehende Einrichtung erhalten.

### Manuelle Installation

1. Kopieren Sie den Ordner `custom_components/sbus` in Ihr `config/custom_components/` Verzeichnis
2. Starten Sie Home Assistant neu

## ⚙️ Konfiguration

### UI-Konfiguration

1. Navigieren Sie zu **Einstellungen** → **Geräte & Dienste**
2. Klicken Sie auf **+ Integration hinzufügen**
3. Suchen Sie nach **SAIA S-Bus**
4. Wählen Sie das gewünschte Protokoll:

#### Ether-S-Bus (UDP/TCP)
- **Connection Type**: UDP (Standard) oder TCP
- **Host**: IP-Adresse oder Hostname der PCD Steuerung
- **Port**: UDP/TCP-Port (Standard: 5050)
- **Station Adresse**: S-Bus Stationsadresse (0-253, Standard: 0)
- **Scan Intervall**: Abfrageintervall in Sekunden (Standard: 30)

#### Serial-S-Bus (RS-232/RS-485)
- **Connection Type**: USB/Serial oder TCP-Seriell-Bridge
- **Serial Port**: 
  - USB/Serial: z.B. `/dev/ttyUSB0`, `/dev/ttyAMA0`
  - TCP-Seriell-Bridge: z.B. `192.168.1.100:5050`
- **Baud Rate**: 9600, 19200, 38400, 57600, 115200 (Standard: 9600)
- **Station Adresse**: S-Bus Stationsadresse (0-253, Standard: 0)
- **Scan Intervall**: Abfrageintervall in Sekunden (Standard: 30)

#### Profi-S-Bus (Profibus Gateway)
- **Gateway Host**: IP-Adresse des Profibus-Gateways
- **Gateway Port**: TCP-Port des Gateways
- **Station Adresse**: S-Bus Stationsadresse (0-253)
- **Profibus Adresse**: Profibus-Knotennummer (0-126)
- **Scan Intervall**: Abfrageintervall in Sekunden (Standard: 30)

### Auto-Discovery

Die Integration unterstützt automatische Erkennung von PCD Steuerungen im Netzwerk:

- **mDNS/Zeroconf**: Erkennung über `_http._tcp.local.` und `_sbus._tcp.local.`
- **SSDP**: Erkennung von SAIA-Geräten mit Herstellerinformation

Wenn eine Steuerung gefunden wird, erscheint eine Benachrichtigung in Home Assistant mit vorausgefüllten Verbindungsdaten.

## 📖 Verwendung

### Entitäten

Welche Register und Flags als Entitäten angelegt werden, legst du unter
**Einstellungen → Geräte & Dienste → SAIA S-Bus → Konfigurieren** fest:

- **Register hinzufügen** → Sensor, oder mit „Beschreibbar“ ein Zahlenfeld
  zum Einstellen (z. B. Sollwerte). Wert = Rohwert × Faktor.
  - *Datentyp*: Ganzzahl mit/ohne Vorzeichen oder Gleitkomma (IEEE 754)
  - *Faktor*: z. B. `0.1`, wenn die PCD 32,5 °C als `325` ablegt
  - *Einheit*: °C, kWh, W, bar … setzen automatisch den passenden Sensortyp
    (Temperatur, Energie, Leistung, Druck …)
- **Flag hinzufügen** → Binärsensor (nur lesen) oder Schalter (beschreibbar)
- Register bearbeiten, Register/Flags entfernen, Abfrageintervall ändern

Nah beieinander liegende Adressen werden mit einem Telegramm gelesen.
Solange nichts konfiguriert ist, werden wie bisher R 0–9, F 0–31 und Schalter
für F 0–7 angelegt; diese verschwinden, sobald der erste Datenpunkt
konfiguriert wird.

### Datenpunkte aus dem PG5-Projekt übernehmen

Statt Adressen einzutippen, kannst du die Datenpunkte direkt aus dem
PG5-Projekt wählen, das auf der PCD läuft:

1. Projekt in PG5 bauen (damit die Adressen aktuell sind).
2. **Konfigurieren → PG5-Projekt importieren** und die Dateien hochladen:
   - die Fupla-Datei, z. B. `HKLS.fup`
   - die Linker-Map aus dem Ordner `Lst`, z. B. `Lst/Mardelle5.map`
   - optional die **DDC-Suite-Bibliothek**: ein ZIP mit den Dateien
     `DDC27_FAM_*_de.idx` aus dem Bibliotheksordner von PG5 (siehe unten)
3. **Datenpunkte aus Projekt wählen**: Anlage wählen (z. B. „S01“) und dann
   - **ganze Anlagenteile** ankreuzen, z. B. „S01 Zirk. UWP – 14 (3 ✎)“:
     alle Datenpunkte des Anlagenteils werden übernommen, oder
   - **einzelne Datenpunkte** aus einer Liste mit Klartext-Namen und
     Beschreibungen, z. B.
     „Speicher Temp. 2 – Istwert: Physikalischer Wert des Sensors (R 3187)“.

Ein Anlagenteil ist alles, was in der DDC Suite dieselbe FBox-Beschreibung
trägt (z. B. Pumpen- und Störmeldungs-FBox von „Zirk. UWP“). Jeder
Anlagenteil wird ein eigenes Gerät unter der PCD. Auf dessen Geräteseite
stehen alle Datenpunkte beisammen, und **Zum Dashboard hinzufügen** legt
daraus mit einem Klick eine Karte an. Die Entitäten heißen dort kurz wie in
der DDC Suite („Betrieb“, „BrmSm“), die Beschreibung steht im Attribut
`description`.

Standardmäßig erscheinen die Betriebswerte (DDC-Suite-Stufen 1–3: Istwerte,
Sollwerte, Zustände, Meldungen). Mit „Auch Einstell- und
Inbetriebnahme-Parameter anzeigen“ kommen die Stufen 4 und 5 dazu.

Name, Faktor (aus dem Anzeigeformat, z. B. eine Nachkommastelle → 0,1),
Einheit und Wertebereich werden aus dem Projekt übernommen. Einstellbare
Werte (✎) werden zu Zahlenfeldern bzw. Schaltern, Anzeigewerte zu Sensoren
bzw. Binärsensoren.

#### Lesbare Namen und Werte-Texte (DDC-Suite-Bibliothek)

Mit der Bibliothek übernimmt die Integration die Bezeichnungen und
Auswahltexte, die PG5 im Einstellfenster der FBox anzeigt:

| Datenpunkt | Wird zu | Beispiel |
|---|---|---|
| Einstellbarer Auswahlwert | Auswahlfeld | „HMI Niederprior“: Auto / Aus / Ein |
| Angezeigter Auswahlwert | Sensor mit Text | „HMI Höherprior“: Auto |
| Meldung | Binärsensor, Attribut `state_text` | „Motorstörungen“: keine / STÖRUNG |
| Übrige Werte | lesbarer Name | „Rückmeldung“ statt `Betrieb` |

Werte, die in der Bibliothek nicht vorkommen, werden als Zahl angezeigt.
Gespeichert werden nur die Texte der verwendeten FBoxen, nicht das ZIP. Lädst
du beim nächsten Import keine Bibliothek hoch, bleiben die bisherigen Texte
erhalten. Die `.idx`-Dateien liegen im PG5-Bibliotheksordner der DDC Suite
(z. B. `…\Libs\…\DDC Suite 2.7\`); am besten alle `DDC27_FAM_*_de.idx`
als ZIP packen, damit die Umlaute erhalten bleiben.

Ändert sich das Programm und PG5 vergibt neue Adressen, importierst du die
Dateien einfach erneut: Die gewählten Datenpunkte werden über ihren
Symbolnamen auf die neuen Adressen umgestellt, Entitäten und Verlauf bleiben
erhalten. Gespeichert wird nur die ausgewertete Datenpunktliste, nicht die
Dateien.

Einheiten werden bisher nur für die DDC-Suite-Codes °C und % gesetzt; andere
Einheiten lassen sich unter **Register bearbeiten** ergänzen.

Den richtigen Datentyp und Faktor findest du am schnellsten mit der Aktion
`sbus.read_register` (siehe unten): Sie zeigt jeden Wert roh, mit Vorzeichen,
hexadezimal und als Gleitkommazahl.

### Beispiel-Automation

```yaml
automation:
  - alias: "Temperatur überwachen"
    trigger:
      - platform: numeric_state
        entity_id: sensor.pcd3_m5540_vorlauf
        above: 25
    action:
      - service: notify.notify
        data:
          message: "Temperatur überschreitet 25°C!"
```

### Services

Die Integration bietet Custom Services für direkten Zugriff:

#### `sbus.read_register`
Liest ein oder mehrere Register aus und gibt die Werte als Antwort zurück
(in den Entwicklerwerkzeugen unter **Aktionen** sichtbar).

```yaml
service: sbus.read_register
data:
  device_id: <device_id>
  start_address: 100
  count: 4
```

#### `sbus.write_register`
Schreibt einen Wert in ein Register.

```yaml
service: sbus.write_register
data:
  device_id: <device_id>
  address: 100
  value: 12345
```

## 🔧 Technische Details

### S-Bus Protokoll-Varianten

Diese Integration implementiert alle drei SAIA S-Bus Protokoll-Varianten:

#### Ether-S-Bus (UDP/TCP)
- **Modus**: Ether-S-Bus über UDP Port 5050 (Standard) oder TCP
- **Header**: 8-Byte Ether-S-Bus Header mit Sequenznummern
- **CRC**: CRC-16-CCITT mit 0x0000 Initialwert (Polynom 0x1021)
- **Retry**: 3 Versuche mit exponential backoff (0.5s, 1s, 2s)
- **Discovery**: mDNS/Zeroconf und SSDP Support

#### Serial-S-Bus (RS-232/RS-485)
- **Modus**: Data Mode (SM2) mit 8N1 (8 Datenbits, No Parity, 1 Stopbit)
- **Byte-Stuffing**: Automatische Behandlung von 0xB5/0xC5 Escape-Sequenzen
- **CRC**: CRC-16-CCITT über entstuffte Daten
- **Baudraten**: 1200-115200 Baud (Standard: 9600)
- **Verbindungen**: Direkte USB/Serial oder TCP-Seriell-Bridge (ser2net)

#### Profi-S-Bus (Profibus FDL)
- **Transport**: Profibus FDL Layer 2
- **Gateway**: Benötigt Profibus-zu-Ethernet Gateway
- **Adressierung**: Separate Profibus- und S-Bus-Adressen

### Geräteinformationen

Beim Einrichten fragt die Integration die PCD mit dem S-Bus-Befehl
„Read Program Version“ (`0x20`) nach CPU-Typ und Firmware-Version. Beides
erscheint in den Geräteinformationen als Modell und Firmware, z. B.
„PCD3.M53“ und „1.28“. Die PCD liefert dabei nur die CPU-Familie (nicht die
vollständige Artikelnummer wie PCD3.M5360) und nur Haupt- und Nebenversion
der Firmware (nicht 1.28.51). Kennt eine PCD
den Befehl nicht, prüft ein Registerzugriff, ob sie erreichbar ist.

Eine Seriennummer lässt sich über S-Bus nicht in dokumentierter Form
auslesen. Als Gerätekennung dient deshalb IP-Adresse, Port und Station
(bzw. serielle Schnittstelle und Station).

Bei Serial-S-Bus wird die Firmware nicht abgefragt, weil die Länge der
Antwort dort nicht erkennbar ist.

### Architektur

- **Config Flow**: Multi-Step UI-basierte Konfiguration mit Protokollauswahl
- **DataUpdateCoordinator**: Zentrale Datenverwaltung mit Connection Health Monitoring
- **Auto-Reconnect**: Automatische Wiederverbindung bei bis zu 3 aufeinanderfolgenden Fehlern
- **Async/Await**: Nicht-blockierende I/O-Operationen
- **Type Hints**: Vollständige Type-Annotations für bessere Code-Qualität
- **Factory Pattern**: Dynamische Instanziierung der korrekten Protokoll-Implementierung

## 🤝 Beiträge

Beiträge sind willkommen! Bitte lesen Sie [CONTRIBUTING.md](CONTRIBUTING.md) für Details.

### Development Setup

1. Clone das Repository
2. Öffnen Sie den Ordner in VS Code
3. Wenn Sie dazu aufgefordert werden, öffnen Sie den Ordner im Dev Container
4. Der Container wird automatisch eingerichtet mit allen Dependencies

```bash
# Starten Sie Home Assistant im Debug-Modus
hass -c config --debug
```

## 📝 Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe [LICENSE](LICENSE) für Details.

## 🙏 Danksagung

- [MrTir1995](https://github.com/MrTir1995) für die ursprüngliche Integration

- [SAIA-Burgess Controls](https://www.saia-pcd.com/) für das S-Bus Protokoll
- [Home Assistant Community](https://www.home-assistant.io/) für das großartige Framework
- [digimat.saia](https://github.com/digimat/digimat-saia) für die Python S-Bus Referenzimplementierung

## 📞 Support

Bei Problemen oder Fragen:

- Öffnen Sie ein [Issue auf GitHub](https://github.com/jfmennedy/HA-S_BUS/issues)
- Diskutieren Sie im [Home Assistant Forum](https://community.home-assistant.io/)

---

[commits-shield]: https://img.shields.io/github/commit-activity/y/jfmennedy/HA-S_BUS.svg?style=for-the-badge
[commits]: https://github.com/jfmennedy/HA-S_BUS/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[license-shield]: https://img.shields.io/github/license/jfmennedy/HA-S_BUS.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-jfmennedy-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/v/release/jfmennedy/HA-S_BUS.svg?style=for-the-badge
[releases]: https://github.com/jfmennedy/HA-S_BUS/releases
