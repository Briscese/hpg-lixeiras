"""Recebe posicoes do Traccar e publica telemetria MQTT no ThingsBoard.

Configuracao por variaveis de ambiente:
  TB_MQTT_DEVICES       JSON com IMEI -> token MQTT (recomendado para varios rastreadores)
  TB_MQTT_USERNAME      token/usuario MQTT para um unico dispositivo, usado como compatibilidade
  TB_MQTT_HOST          padrao: thingsboard.iot8.com.br
  TB_MQTT_PORT          padrao: 1883
  BRIDGE_SHARED_SECRET  obrigatorio; deve coincidir com o header do Traccar
  BRIDGE_PORT           padrao: 9000
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import struct
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
MQTT_HOST = os.getenv("TB_MQTT_HOST", "thingsboard.iot8.com.br")
MQTT_PORT = int(os.getenv("TB_MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("TB_MQTT_USERNAME", "")
try:
    MQTT_DEVICES = json.loads(os.getenv("TB_MQTT_DEVICES", "{}"))
except json.JSONDecodeError as error:
    raise SystemExit(f"TB_MQTT_DEVICES nao contem JSON valido: {error}") from error
SHARED_SECRET = os.getenv("BRIDGE_SHARED_SECRET", "")
PORT = int(os.getenv("BRIDGE_PORT", "9000"))
DATABASE_PATH = os.getenv("TELEMETRY_DB_PATH", os.path.join(os.path.dirname(__file__), "telemetria.db"))


def initialize_database() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_records (
                id INTEGER PRIMARY KEY,
                received_at_ms INTEGER NOT NULL,
                traccar_position_id INTEGER UNIQUE,
                device_imei TEXT,
                device_name TEXT,
                fix_time TEXT,
                valid_gnss INTEGER,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                speed REAL,
                course REAL,
                accuracy REAL,
                telemetry_json TEXT NOT NULL,
                raw_payload_json TEXT NOT NULL,
                thingsboard_published INTEGER NOT NULL DEFAULT 0,
                thingsboard_error TEXT
            )
            """
        )
        # O forwarder JSON do Traccar pode publicar position.id como 0. Isso nao e um ID unico.
        connection.execute("UPDATE telemetry_records SET traccar_position_id = NULL WHERE traccar_position_id <= 0")


def save_record(payload: dict[str, Any], telemetry: dict[str, Any]) -> int:
    position = payload.get("position", payload)
    device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
    if not isinstance(position, dict):
        raise ValueError("O JSON nao contem um objeto position valido")

    position_id = position.get("id")
    unique_position_id = position_id if isinstance(position_id, int) and position_id > 0 else None
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO telemetry_records (
                received_at_ms, traccar_position_id, device_imei, device_name, fix_time,
                valid_gnss, latitude, longitude, altitude, speed, course, accuracy,
                telemetry_json, raw_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp_ms(position.get("serverTime")) or int(datetime.now().timestamp() * 1000),
                unique_position_id,
                device.get("uniqueId"),
                device.get("name"),
                position.get("fixTime"),
                int(bool(position.get("valid"))),
                position.get("latitude"),
                position.get("longitude"),
                position.get("altitude"),
                position.get("speed"),
                position.get("course"),
                position.get("accuracy"),
                json.dumps(telemetry, separators=(",", ":")),
                json.dumps(payload, separators=(",", ":")),
            ),
        )
        if cursor.rowcount:
            return int(cursor.lastrowid)
        row = connection.execute(
            "SELECT id FROM telemetry_records WHERE traccar_position_id = ?", (unique_position_id,)
        ).fetchone() if unique_position_id is not None else None
        if row is None:
            raise RuntimeError("Nao foi possivel gravar a telemetria no banco local")
        return int(row[0])


def update_publish_status(record_id: int, published: bool, error: str | None = None) -> None:
    with sqlite3.connect(DATABASE_PATH, timeout=15) as connection:
        connection.execute(
            "UPDATE telemetry_records SET thingsboard_published = ?, thingsboard_error = ? WHERE id = ?",
            (int(published), error, record_id),
        )


def timestamp_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value if value > 10_000_000_000 else value * 1000)
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def scalar_values(values: dict[str, Any]) -> dict[str, bool | int | float | str]:
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, (bool, int, float, str)) and value is not None
    }


def to_thingsboard(payload: dict[str, Any]) -> dict[str, Any]:
    position = payload.get("position", payload)
    if not isinstance(position, dict):
        raise ValueError("O JSON nao contem um objeto position valido")

    values = scalar_values(position.get("attributes", {}))
    for source, target in {
        "latitude": "latitude",
        "longitude": "longitude",
        "altitude": "altitude",
        "speed": "speed",
        "course": "course",
        "accuracy": "accuracy",
        "valid": "valid",
        "outdated": "outdated",
    }.items():
        if source in position:
            values[target] = position[source]

    device = payload.get("device")
    if isinstance(device, dict):
        if "uniqueId" in device:
            values["imei"] = str(device["uniqueId"])
        if "name" in device:
            values["deviceName"] = str(device["name"])

    if "latitude" not in values or "longitude" not in values:
        raise ValueError("Posicao sem latitude/longitude")

    result: dict[str, Any] = {"values": values}
    timestamp = timestamp_ms(position.get("fixTime") or position.get("deviceTime"))
    if timestamp is not None:
        result["ts"] = timestamp
    return result


def has_valid_coordinates(payload: dict[str, Any]) -> bool:
    position = payload.get("position", payload)
    if not isinstance(position, dict) or position.get("valid") is not True:
        return False
    latitude = position.get("latitude")
    longitude = position.get("longitude")
    return isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)) and (latitude != 0 or longitude != 0)


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
    multiplier, remaining = 1, 0
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


def mqtt_username_for(payload: dict[str, Any]) -> str:
    device = payload.get("device")
    imei = device.get("uniqueId") if isinstance(device, dict) else None
    if MQTT_DEVICES:
        if not isinstance(imei, str) or imei not in MQTT_DEVICES:
            raise RuntimeError(f"IMEI nao configurado para encaminhamento MQTT: {imei}")
        return str(MQTT_DEVICES[imei])
    if MQTT_USERNAME:
        return MQTT_USERNAME
    raise RuntimeError("Defina TB_MQTT_DEVICES ou TB_MQTT_USERNAME")


def publish(telemetry: dict[str, Any], mqtt_username: str) -> None:

    client_id = f"traccar-{os.getpid()}"
    # MQTT 3.1.1: clean session + username; nao ha campo de senha neste dispositivo.
    connect_body = b"\x00\x04MQTT\x04\x82\x00\x1E" + mqtt_string(client_id) + mqtt_string(mqtt_username)
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


class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/traccar/position":
            self.send_error(404, "Endpoint nao encontrado")
            return
        if not SHARED_SECRET or self.headers.get("X-Bridge-Key") != SHARED_SECRET:
            self.send_error(401, "Chave de integracao invalida")
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw)
            telemetry = to_thingsboard(payload)
            record_id = save_record(payload, telemetry) if has_valid_coordinates(payload) else None
            try:
                publish(telemetry, mqtt_username_for(payload))
            except RuntimeError as error:
                if record_id is not None:
                    update_publish_status(record_id, False, str(error))
                raise
            if record_id is not None:
                update_publish_status(record_id, True)
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            print(f"ERRO: {error}", flush=True)
            self.send_error(502, str(error))
            return

        print(f"OK: {telemetry}", flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"HTTP: {format % args}", flush=True)


if __name__ == "__main__":
    if (not MQTT_USERNAME and not MQTT_DEVICES) or not SHARED_SECRET:
        raise SystemExit("Defina TB_MQTT_DEVICES (ou TB_MQTT_USERNAME) e BRIDGE_SHARED_SECRET antes de iniciar a ponte.")
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), BridgeHandler)
    print(f"Ponte ouvindo em http://127.0.0.1:{PORT}/traccar/position", flush=True)
    print(f"Banco local: {DATABASE_PATH}", flush=True)
    server.serve_forever()
