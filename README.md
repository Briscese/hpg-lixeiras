# GPS-lixeiras

Rastreamento GPS de lixeiras.

## Teltonika to ThingsBoard receiver

Receives Teltonika Codec 8 and Codec 8 Extended packets directly by TCP, stores every decoded packet in SQLite, and publishes telemetry to ThingsBoard MQTT. The current scope is ATC700 and TAT141.

## Local setup

1. Stop Traccar if it is using TCP port 29626.
2. Copy `start_teltonika_receiver.example.ps1` to `start_teltonika_receiver.ps1`.
3. Fill the IMEI to ThingsBoard access-token mapping.
4. Start the receiver:

```powershell
.\start_teltonika_receiver.ps1
```

The local SQLite database is created as `telemetria.db`. Use `export_teltonika_csv.ps1` to export direct Teltonika records.

For direct AWS operation, configure each Teltonika tracker with `thingsboard.iot8.com.br` as its TCP server and port `29626`. The AWS Security Group and operating-system firewall must allow inbound TCP port `29626`.

## Dashboard

In a second PowerShell window, run:

```powershell
.\start_telemetry_dashboard.ps1
```

Open `http://127.0.0.1:8787`. The dashboard reads the database without changing it, refreshes every 15 seconds and offers device and valid-GPS filters.

For AWS, run the dashboard on the same instance as the receiver, keep it bound to `127.0.0.1`, and use `nginx-telemetry-dashboard.conf.example` as the HTTPS reverse-proxy template. Publish a protected hostname such as `https://telemetria.iot8.com.br`; do not expose SQLite or port 8787 directly.
