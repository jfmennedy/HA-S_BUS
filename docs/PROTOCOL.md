# S-Bus Protokoll - Technische Referenz

## Übersicht

Diese Integration implementiert das SAIA S-Bus Protokoll (Data Mode SM2) für die Kommunikation mit PCD Steuerungen über Ether-S-Bus (UDP).

## Protokoll-Details

### Telegram-Struktur (Ether-S-Bus)

```
Offset | Feld       | Größe | Beschreibung
-------|------------|-------|------------------------------------
0      | Length     | 4     | Gesamtlänge (Big Endian)
4      | Version    | 1     | Protokollversion (0x01)
5      | Type       | 1     | Protokolltyp (0x00 = Data)
6      | Sequence   | 2     | Sequenznummer (Big Endian)
8      | Attribute  | 1     | 0x00=Request, 0x01=Response, 0x02=ACK
9      | Address    | 1     | Station Address (0-253)
10     | Command    | 1     | S-Bus Opcode
11..n  | Data       | var   | Nutzdaten
n+1    | CRC High   | 1     | CRC-16 High Byte
n+2    | CRC Low    | 1     | CRC-16 Low Byte
```

### CRC-16-CCITT

- **Polynom:** 0x1021 (x^16 + x^12 + x^5 + 1)
- **Initialisierung:** 0x0000
- **Reflection:** Keine
- **Byte Order:** Big Endian
- **Berechnung:** Über gesamtes Telegram (inkl. Length-Feld)

### Opcodes

| Opcode | Objekt    | Operation | Beschreibung                    |
|--------|-----------|-----------|----------------------------------|
| 0x00   | Counter   | Read      | Counter lesen                   |
| 0x02   | Flag      | Read      | Flags (Bits) lesen              |
| 0x03   | Input     | Read      | Digitale Eingänge lesen         |
| 0x04   | RTC       | Read      | Real-Time Clock lesen           |
| 0x05   | Output    | Read      | Digitale Ausgänge lesen         |
| 0x06   | Register  | Read      | Register (32-Bit) lesen         |
| 0x07   | Timer     | Read      | Timer lesen                     |
| 0x0A   | Counter   | Write     | Counter schreiben               |
| 0x0B   | Flag      | Write     | Flag schreiben                  |
| 0x0C   | RTC       | Write     | Real-Time Clock schreiben       |
| 0x0D   | Output    | Write     | Digitalen Ausgang schreiben     |
| 0x0E   | Register  | Write     | Register schreiben              |
| 0x0F   | Timer     | Write     | Timer schreiben                 |

### Geräte-Identifikation

PCDs haben keine festen „Systemregister“ für Typ oder Firmware: R 0 und
folgende sind gewöhnliche Programmregister. Typ und Firmware liefert der
Befehl **Read Program Version** (`0x20`, ohne Nutzdaten). Die Antwort ist
ASCII-Text: 5 Zeichen CPU-Typ, danach die Firmware-Version
(z. B. `D3M53` + `1.28`).

Weitere Status-Befehle: `0x1B` Read PCD Status (`R` = Run, `S` = Stop,
`H` = Halt), `0x1D` Read Station Number.

## Implementierungsdetails

### Read Register Request

```python
# Register 100 lesen (1 Register)
data = struct.pack("!HB", 100, 1)  # Address + Count
telegram = build_telegram(CMD_READ_REGISTER, data)
```

**Request Data:**
- Bytes 0-1: Register Address (Big Endian, 2 Bytes)
- Byte 2: Count (1-32)

**Response Data:**
- Jedes Register: 4 Bytes (Big Endian, 32-Bit Integer)

### Write Register Request

```python
# Register 100 = 12345 schreiben
data = struct.pack("!HI", 100, 12345)  # Address + Value
telegram = build_telegram(CMD_WRITE_REGISTER, data)
```

**Request Data:**
- Bytes 0-1: Register Address (2 Bytes)
- Bytes 2-5: Value (4 Bytes, 32-Bit Integer)

**Response:** ACK (keine Daten)

### Read Flags Request

```python
# 8 Flags ab Adresse 0 lesen
data = struct.pack("!HH", 0, 8)  # Start Address + Count
telegram = build_telegram(CMD_READ_FLAG, data)
```

**Request Data:**
- Bytes 0-1: Start Address (2 Bytes)
- Bytes 2-3: Count (2 Bytes)

**Response Data:**
- Flags gepackt in Bytes (8 Flags pro Byte)
- Bit 0 = LSB, Bit 7 = MSB

### Write Flag Request

```python
# Flag 5 = True schreiben
data = struct.pack("!HB", 5, 1)  # Address + Value (0 oder 1)
telegram = build_telegram(CMD_WRITE_FLAG, data)
```

**Request Data:**
- Bytes 0-1: Flag Address (2 Bytes)
- Byte 2: Value (0 = False, 1 = True)

**Response:** ACK

## Error Handling

### Timeouts

- **Standard:** 5 Sekunden
- **Konfigurierbar** in Protocol-Konstruktor
- **Retry-Logik:** Implementiert im Coordinator

### CRC-Fehler

- Automatische Validierung bei Empfang
- Bei Fehler: `SBusCRCError` Exception
- Logged als ERROR

### Connection Errors

- Bei UDP: Keine explizite Connection
- "Connection Error" = Timeout bei erster Anfrage
- Device Info Read zum Verbindungstest

## Performance-Optimierung

### Batch-Reads

Mehrere Register auf einmal lesen (bis zu 32):

```python
# Register 100-109 lesen (10 Register)
values = await protocol.read_registers(100, 10)
```

### Coordinator Pattern

- **Zentrale Datenerfassung:** Ein Request für alle Entitäten
- **Datenkonsistenz:** Alle Entitäten sehen denselben Snapshot
- **Rate Limiting:** Konfigurierbare Scan-Intervalle

### Async/Await

- **Nicht-blockierend:** Keine Blockierung der Event Loop
- **Concurrent Requests:** Möglich mit asyncio.gather()
- **Timeout-Handling:** Graceful mit asyncio.wait_for()

## Beispiele

### Einfaches Read

```python
from custom_components.sbus.sbus_protocol import SBusProtocol

protocol = SBusProtocol("192.168.1.100", 5050, 0)
await protocol.connect()

# Register lesen
values = await protocol.read_registers(100, 4)
print(f"Register 100-103: {values}")

await protocol.disconnect()
```

### Device Info

```python
device_info = await protocol.get_device_info()
print(f"Device: {device_info['product_type']}")
print(f"Serial: {device_info['serial_number']}")
print(f"Firmware: {device_info['firmware_version']}")
```

### Flags schreiben

```python
# Flag 0 setzen
await protocol.write_flag(0, True)

# Flag 0 löschen
await protocol.write_flag(0, False)
```

## Referenzen

- [SAIA PCD Manual SAIA S-Bus](https://www.dcsmodule.com/js/htmledit/kindeditor/attached/20220712/20220712134948_56336.pdf)
- [S-BUS Protocol for MORSE](https://www.racom.eu/download/sw/prot/free/eng/sbus.pdf)
- [Wireshark S-Bus Dissector](https://github.com/boundary/wireshark/blob/master/epan/dissectors/packet-sbus.c)
