"""Read-only local web dashboard for the Teltonika SQLite database."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DATABASE_PATH = Path(os.getenv("TELEMETRY_DB_PATH", Path(__file__).with_name("telemetria.db")))
HOST = os.getenv("TELEMETRY_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("TELEMETRY_DASHBOARD_PORT", "8787"))

HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Telemetria Teltonika</title><style>
body{margin:0;background:#f3f6f8;color:#17283b;font:14px Arial,sans-serif}header{background:#073b75;color:#fff;padding:17px 24px;display:flex;gap:18px;align-items:center}h1{font-size:20px;margin:0}#updated{opacity:.85;font-size:12px}main{max-width:1300px;margin:auto;padding:20px 24px}.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin-bottom:15px}label{display:grid;gap:5px;font-size:12px;font-weight:bold}input,select,button{padding:8px 10px;border:1px solid #bcc8d3;border-radius:4px;font:inherit;background:#fff}button{background:#0865b2;border-color:#0865b2;color:#fff;cursor:pointer}.summary{display:grid;grid-template-columns:repeat(3,minmax(160px,1fr));gap:12px;margin-bottom:15px}.metric,.table{background:#fff;border:1px solid #d8e0e8;border-radius:5px}.metric{padding:13px}.metric span{display:block;color:#5a6b7e;font-size:12px}.metric strong{font-size:19px}.table{overflow:auto}table{border-collapse:collapse;width:100%;min-width:930px}th,td{padding:10px 12px;border-bottom:1px solid #e1e7ed;text-align:left;white-space:nowrap}th{background:#edf2f6;color:#415366;font-size:12px}.yes{color:#087441;font-weight:bold}.no{color:#a43a27}.empty{padding:24px;color:#5a6b7e}a{color:#075da9}@media(max-width:640px){main{padding:15px}.summary{grid-template-columns:1fr}}
</style></head><body><header><h1>Telemetria Teltonika</h1><span id="updated">Carregando...</span></header><main>
<div class="toolbar"><label>Dispositivo<select id="device"><option value="">Todos</option></select></label><label>Registros<input id="limit" type="number" min="10" max="1000" value="100"></label><label><span>Filtro</span><span><input id="valid" type="checkbox"> Apenas GPS válido</span></label><button id="refresh">Atualizar</button></div>
<section class="summary"><div class="metric"><span>Registros exibidos</span><strong id="count">-</strong></div><div class="metric"><span>Última posição válida</span><strong id="last">-</strong></div><div class="metric"><span>Banco</span><strong id="database">-</strong></div></section>
<div class="table"><table><thead><tr><th>Data e hora</th><th>Dispositivo</th><th>GPS</th><th>Coordenadas</th><th>Velocidade</th><th>Satélites</th><th>Bateria</th><th>ThingsBoard</th></tr></thead><tbody id="rows"></tbody></table><div id="empty" class="empty" hidden>Nenhum registro encontrado.</div></div>
</main><script>
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function devices(){let d=await(await fetch('/api/devices')).json(),s=document.querySelector('#device');d.devices.forEach(x=>s.insertAdjacentHTML('beforeend',`<option value="${esc(x.imei)}">${esc(x.name)} (${esc(x.imei)})</option>`));}
async function refresh(){let p=new URLSearchParams({limit:document.querySelector('#limit').value}),imei=document.querySelector('#device').value;if(imei)p.set('imei',imei);if(document.querySelector('#valid').checked)p.set('valid','1');let d=await(await fetch('/api/records?'+p)).json(),body=document.querySelector('#rows');body.innerHTML='';d.records.forEach(r=>{let c=r.valid_gnss?`<a target="_blank" rel="noreferrer" href="https://www.openstreetmap.org/?mlat=${r.latitude}&mlon=${r.longitude}#map=17/${r.latitude}/${r.longitude}">${r.latitude.toFixed(7)}, ${r.longitude.toFixed(7)}</a>`:'Sem fix';body.insertAdjacentHTML('beforeend',`<tr><td>${esc(r.local_time)}</td><td>${esc(r.device_name||r.device_imei)}</td><td class="${r.valid_gnss?'yes':'no'}">${r.valid_gnss?'Válido':'Inválido'}</td><td>${c}</td><td>${r.speed_kph.toFixed(1)} km/h</td><td>${r.satellites}</td><td>${r.battery??'-'}</td><td>${r.thingsboard_published?'Enviado':'Pendente'}</td></tr>`);});document.querySelector('#count').textContent=d.records.length;document.querySelector('#last').textContent=d.last_valid?d.last_valid.local_time:'Sem posição válida';document.querySelector('#database').textContent=d.database_exists?'Conectado':'Não encontrado';document.querySelector('#empty').hidden=!!d.records.length;document.querySelector('#updated').textContent='Atualizado: '+new Date().toLocaleTimeString('pt-BR');}
document.querySelector('#refresh').onclick=refresh;document.querySelector('#device').onchange=refresh;document.querySelector('#valid').onchange=refresh;devices().then(refresh);setInterval(refresh,15000);
</script></body></html>"""


def database_rows(sql: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    if not DATABASE_PATH.exists():
        return []
    connection = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def format_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000).strftime("%d/%m/%Y %H:%M:%S")


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.reply(HTML.encode(), "text/html; charset=utf-8")
        elif parsed.path == "/api/devices":
            rows = database_rows("SELECT device_imei, MAX(device_name) AS device_name FROM teltonika_records GROUP BY device_imei ORDER BY device_name")
            self.reply_json({"devices": [{"imei": r["device_imei"], "name": r["device_name"] or r["device_imei"]} for r in rows]})
        elif parsed.path == "/api/records":
            self.records(parse_qs(parsed.query))
        else:
            self.send_error(404)

    def records(self, query: dict[str, list[str]]) -> None:
        try:
            limit = min(max(int(query.get("limit", ["100"])[0]), 10), 1000)
        except ValueError:
            limit = 100
        conditions: list[str] = []
        values: list[object] = []
        imei = query.get("imei", [""])[0]
        if imei:
            conditions.append("device_imei = ?")
            values.append(imei)
        if query.get("valid", [""])[0] == "1":
            conditions.append("valid_gnss = 1")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = database_rows(f"SELECT * FROM teltonika_records{where} ORDER BY id DESC LIMIT ?", tuple(values + [limit]))
        records = []
        for row in rows:
            attributes = json.loads(row["attributes_json"])
            records.append({"device_imei": row["device_imei"], "device_name": row["device_name"], "local_time": format_time(row["device_time_ms"]), "valid_gnss": bool(row["valid_gnss"]), "latitude": row["latitude"], "longitude": row["longitude"], "speed_kph": row["speed_kph"], "satellites": row["satellites"], "battery": attributes.get("battery"), "thingsboard_published": bool(row["thingsboard_published"])})
        self.reply_json({"records": records, "last_valid": next((item for item in records if item["valid_gnss"]), None), "database_exists": DATABASE_PATH.exists()})

    def reply_json(self, payload: object) -> None:
        self.reply(json.dumps(payload).encode(), "application/json; charset=utf-8")

    def reply(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


if __name__ == "__main__":
    print(f"Painel em http://{HOST}:{PORT}")
    print(f"Banco local: {DATABASE_PATH.resolve()}")
    ThreadingHTTPServer((HOST, PORT), DashboardHandler).serve_forever()
