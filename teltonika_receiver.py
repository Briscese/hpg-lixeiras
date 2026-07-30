"""Direct TCP receiver for Teltonika Codec 8 and Codec 8 Extended devices."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import socketserver
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MQTT_HOST = os.getenv("TB_MQTT_HOST", "thingsboard.iot8.com.br")
MQTT_PORT = int(os.getenv("TB_MQTT_PORT", "1883"))
LISTEN_HOST = os.getenv("TELTONIKA_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("TELTONIKA_LISTEN_PORT", "5027"))
DATABASE_PATH = Path(os.getenv("TELEMETRY_DB_PATH", Path(__file__).with_name("telemetria.db")))
MAX_PACKET_SIZE = 1024 * 1024

try:
    MQTT_DEVICES = json.loads(os.getenv("TB_MQTT_DEVICES", "{}"))
    DEVICE_NAMES = json.loads(os.getenv("TELTONIKA_DEVICE_NAMES", "{}"))
except json.JSONDecodeError as error:
    raise SystemExit(f"Configuracao JSON invalida: {error}") from error

# Standard AVL identifiers that are useful as named telemetry. Every other value
# is retained as io<ID> so no decoded information is discarded.
ATTRIBUTE_NAMES: dict[int, tuple[str, float | None]] = {
    16: ("odometer", 1.0),
    21: ("rssi", 1.0),
    24: ("speedKph", 1.0),
    67: ("battery", 0.001),
    68: ("batteryCurrent", 0.001),
    113: ("batteryLevel", 1.0),
    181: ("pdop", 0.1),
    182: ("hdop", 0.1),
    199: ("tripOdometer", 1.0),
    200: ("sleepMode", 1.0),
    239: ("ignition", None),
    240: ("motion", None),
    241: ("operator", 1.0),
}


def initialize_database() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS teltonika_packets (
                id INTEGER PRIMARY KEY,
                received_at_ms INTEGER NOT NULL,
                imei TEXT NOT NULL,
                remote_address TEXT NOT NULL,
                codec INTEGER NOT NULL,
                record_count INTEGER NOT NULL,
                packet_sha256 TEXT NOT NULL UNIQUE,
                packet_hex TEXT NOT NULL,
                decoded_json TEXT NOT NULL,
                thingsboard_published INTEGER NOT NULL DEFAULT 0,
                thingsboard_error TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS teltonika_records (
                id INTEGER PRIMARY KEY,
                packet_id INTEGER NOT NULL REFERENCES teltonika_packets(id),
                record_index INTEGER NOT NULL,
                device_imei TEXT NOT NULL,
                device_name TEXT,
                device_time_ms INTEGER NOT NULL,
                valid_gnss INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                altitude REAL NOT NULL,
                speed_kph REAL NOT NULL,
                course REAL NOT NULL,
                satellites INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                attributes_json TEXT NOT NULL,
                telemetry_json TEXT NOT NULL,
                thingsboard_published INTEGER NOT NULL DEFAULT 0,
                thingsboard_error TEXT,
                UNIQUE(packet_id, record_index)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_teltonika_records_imei_time "
            "ON teltonika_records(device_imei, device_time_ms)"
        )


def crc16_ibm(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def read_number(data: bytes, offset: int, size: int, signed: bool = False) -> tuple[int, int]:
    end = offset + size
    if end > len(data):
        raise ValueError("Pacote AVL truncado")
    return int.from_bytes(data[offset:end], "big", signed=signed), end


def decode_io_value(io_id: int, value: int) -> tuple[str, int | float | bool]:
    name, scale = ATTRIBUTE_NAMES.get(io_id, (f"io{io_id}", 1.0))
    if io_id in (239, 240):
        return name, bool(value)
    return name, value * scale if scale not in (None, 1.0) else value


def decode_record(data: bytes, offset: int, codec: int) -> tuple[dict[str, Any], int]:
    timestamp, offset = read_number(data, offset, 8)
    priority, offset = read_number(data, offset, 1)
    longitude_raw, offset = read_number(data, offset, 4, signed=True)
    latitude_raw, offset = read_number(data, offset, 4, signed=True)
    altitude, offset = read_number(data, offset, 2, signed=True)
    course, offset = read_number(data, offset, 2)
    satellites, offset = read_number(data, offset, 1)
    speed_kph, offset = read_number(data, offset, 2)

    id_size = 1 if codec == 0x08 else 2
    count_size = 1 if codec == 0x08 else 2
    _, offset = read_number(data, offset, id_size)  # Event I/O ID
    _, offset = read_number(data, offset, count_size)  # Total I/O count
    attributes: dict[str, int | float | bool] = {}

    for value_size in (1, 2, 4, 8):
        value_count, offset = read_number(data, offset, count_size)
        for _ in range(value_count):
            io_id, offset = read_number(data, offset, id_size)
            value, offset = read_number(data, offset, value_size)
            name, decoded = decode_io_value(io_id, value)
            attributes[name] = decoded

    if codec == 0x8E:
        variable_count, offset = read_number(data, offset, 2)
        for _ in range(variable_count):
            io_id, offset = read_number(data, offset, 2)
            length, offset = read_number(data, offset, 2)
            value, offset = read_number(data, offset, length)
            name, decoded = decode_io_value(io_id, value)
            attributes[name] = decoded

    latitude = latitude_raw / 10_000_000
    longitude = longitude_raw / 10_000_000
    return {
        "deviceTimeMs": timestamp,
        "priority": priority,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "course": course,
        "satellites": satellites,
        "speedKph": speed_kph,
        "valid": satellites > 0 and (latitude != 0 or longitude != 0),
        "attributes": attributes,
    }, offset


def decode_packet(data: bytes) -> tuple[int, list[dict[str, Any]]]:
    if len(data) < 3:
        raise ValueError("Pacote AVL curto")
    codec, count = data[0], data[1]
    if codec not in (0x08, 0x8E):
        raise ValueError(f"Codec Teltonika nao suportado: 0x{codec:02X}")
    offset = 2
    records = []
    for _ in range(count):
        record, offset = decode_record(data, offset, codec)
        records.append(record)
    if offset + 1 != len(data) or data[offset] != count:
        raise ValueError("Contagem final AVL invalida")
    return codec, records


def telemetry_for(imei: str, record: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = dict(record["attributes"])
    values.update(
        {
            "imei": imei,
            "deviceName": str(DEVICE_NAMES.get(imei, imei)),
            "latitude": record["latitude"],
            "longitude": record["longitude"],
            "altitude": record["altitude"],
            "speedKph": record["speedKph"],
            "course": record["course"],
            "sat": record["satellites"],
            "priority": record["priority"],
            "valid": record["valid"],
        }
    )
    return {"ts": record["deviceTimeMs"], "values": values}


def save_packet(imei: str, address: str, raw: bytes, codec: int, records: list[dict[str, Any]]) -> int:
    digest = hashlib.sha256(raw).hexdigest()
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO teltonika_packets (
                received_at_ms, imei, remote_address, codec, record_count,
                packet_sha256, packet_hex, decoded_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (int(datetime.now(UTC).timestamp() * 1000), imei, address, codec, len(records), digest,
             raw.hex(), json.dumps(records, separators=(",", ":"))),
        )
        if cursor.rowcount:
            return int(cursor.lastrowid)
        row = connection.execute("SELECT id FROM teltonika_packets WHERE packet_sha256 = ?", (digest,)).fetchone()
        if row is None:
            raise RuntimeError("Nao foi possivel gravar pacote Teltonika")
        return int(row[0])


def save_record(packet_id: int, index: int, imei: str, record: dict[str, Any], telemetry: dict[str, Any]) -> int:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO teltonika_records (
                packet_id, record_index, device_imei, device_name, device_time_ms, valid_gnss,
                latitude, longitude, altitude, speed_kph, course, satellites, priority,
                attributes_json, telemetry_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (packet_id, index, imei, str(DEVICE_NAMES.get(imei, imei)), record["deviceTimeMs"],
             int(record["valid"]), record["latitude"], record["longitude"], record["altitude"],
             record["speedKph"], record["course"], record["satellites"], record["priority"],
             json.dumps(record["attributes"], separators=(",", ":")),
             json.dumps(telemetry, separators=(",", ":"))),
        )
        if cursor.rowcount:
            return int(cursor.lastrowid)
        row = connection.execute(
            "SELECT id FROM teltonika_records WHERE packet_id = ? AND record_index = ?", (packet_id, index)
        ).fetchone()
        if row is None:
            raise RuntimeError("Nao foi possivel gravar registro Teltonika")
        return int(row[0])


def update_publish_status(packet_id: int, record_id: int, published: bool, error: str | None = None) -> None:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        connection.execute(
            "UPDATE teltonika_packets SET thingsboard_published = ?, thingsboard_error = ? WHERE id = ?",
            (int(published), error, packet_id),
        )
        connection.execute(
            "UPDATE teltonika_records SET thingsboard_published = ?, thingsboard_error = ? WHERE id = ?",
            (int(published), error, record_id),
        )


def mqtt_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("!H", len(encoded)) + encoded


def mqtt_remaining_length(length: int) -> bytes:
    result = bytearray()
    while True:
        encoded = length % 128
        length //= 128
        if length:
            encoded |= 0x80
        result.append(encoded)
        if not length:
            return bytes(result)


def mqtt_read_packet(connection: socket.socket) -> tuple[int, bytes]:
    first = connection.recv(1)
    if not first:
        raise RuntimeError("Broker MQTT fechou a conexao")
    multiplier = 1
    remaining = 0
    while True:
        byte = connection.recv(1)
        if not byte:
            raise RuntimeError("Pacote MQTT incompleto")
        remaining += (byte[0] & 0x7F) * multiplier
        if not byte[0] & 0x80:
            break
        multiplier *= 128
    payload = bytearray()
    while len(payload) < remaining:
        chunk = connection.recv(remaining - len(payload))
        if not chunk:
            raise RuntimeError("Pacote MQTT incompleto")
        payload.extend(chunk)
    return first[0], bytes(payload)


def publish(telemetry: dict[str, Any], token: str) -> None:
    client_id = f"teltonika-{os.getpid()}"
    connect_body = b"\x00\x04MQTT\x04\x82\x00\x1E" + mqtt_string(client_id) + mqtt_string(token)
    connect_packet = b"\x10" + mqtt_remaining_length(len(connect_body)) + connect_body
    packet_id = 1
    payload = json.dumps(telemetry, separators=(",", ":")).encode("utf-8")
    publish_body = mqtt_string("v1/devices/me/telemetry") + struct.pack("!H", packet_id) + payload
    publish_packet = b"\x32" + mqtt_remaining_length(len(publish_body)) + publish_body
    try:
        with socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=15) as connection:
            connection.settimeout(15)
            connection.sendall(connect_packet)
            packet_type, response = mqtt_read_packet(connection)
            if packet_type != 0x20 or response != b"\x00\x00":
                raise RuntimeError(f"Conexao MQTT recusada: {response.hex()}")
            connection.sendall(publish_packet)
            packet_type, response = mqtt_read_packet(connection)
            if packet_type != 0x40 or response != struct.pack("!H", packet_id):
                raise RuntimeError("Broker MQTT nao confirmou a telemetria")
    except OSError as error:
        raise RuntimeError(f"Falha ao conectar ao MQTT: {error}") from error


def read_exact(stream: Any, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ConnectionError("Conexao Teltonika encerrada durante a leitura")
    return data


class TeltonikaHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        imei_length = struct.unpack("!H", read_exact(self.rfile, 2))[0]
        if not 10 <= imei_length <= 32:
            raise ValueError("Comprimento de IMEI invalido")
        imei = read_exact(self.rfile, imei_length).decode("ascii")
        if imei not in MQTT_DEVICES:
            self.wfile.write(b"\x00")
            self.wfile.flush()
            print(f"IMEI recusado: {imei}", flush=True)
            return

        self.wfile.write(b"\x01")
        self.wfile.flush()
        print(f"Teltonika conectado: {imei} de {self.client_address[0]}", flush=True)
        while True:
            header = self.rfile.read(8)
            if not header:
                return
            if len(header) != 8:
                raise ConnectionError("Cabecalho Teltonika incompleto")
            preamble, data_length = struct.unpack("!II", header)
            if preamble != 0 or not 1 <= data_length <= MAX_PACKET_SIZE:
                raise ValueError("Cabecalho Teltonika invalido")
            data = read_exact(self.rfile, data_length)
            expected_crc = struct.unpack("!I", read_exact(self.rfile, 4))[0] & 0xFFFF
            if crc16_ibm(data) != expected_crc:
                raise ValueError("CRC Teltonika invalido")
            codec, records = decode_packet(data)
            packet_id = save_packet(imei, self.client_address[0], header + data, codec, records)
            for index, record in enumerate(records):
                telemetry = telemetry_for(imei, record)
                record_id = save_record(packet_id, index, imei, record, telemetry)
                try:
                    publish(telemetry, str(MQTT_DEVICES[imei]))
                except RuntimeError as error:
                    update_publish_status(packet_id, record_id, False, str(error))
                    raise
                update_publish_status(packet_id, record_id, True)
            self.wfile.write(struct.pack("!I", len(records)))
            self.wfile.flush()
            print(f"OK: {imei} codec=0x{codec:02X} registros={len(records)}", flush=True)


class ThreadingTeltonikaServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    if not isinstance(MQTT_DEVICES, dict) or not MQTT_DEVICES:
        raise SystemExit("Defina TB_MQTT_DEVICES com IMEI -> token ThingsBoard.")
    if not isinstance(DEVICE_NAMES, dict):
        raise SystemExit("TELTONIKA_DEVICE_NAMES deve ser um JSON de IMEI -> nome.")
    initialize_database()
    with ThreadingTeltonikaServer((LISTEN_HOST, LISTEN_PORT), TeltonikaHandler) as server:
        print(f"Receptor Teltonika ouvindo em {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
        print(f"Banco local: {DATABASE_PATH}", flush=True)
        server.serve_forever()
