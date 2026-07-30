# GPS-lixeiras

Rastreamento GPS de lixeiras.

## Teltonika to ThingsBoard receiver

Receives Teltonika Codec 8 and Codec 8 Extended packets directly by TCP, stores every decoded packet in SQLite, and publishes telemetry to ThingsBoard MQTT. The current scope is ATC700 and TAT141.

## Local setup

1. Stop Traccar if it is using TCP port 5027.
2. Copy `start_teltonika_receiver.example.ps1` to `start_teltonika_receiver.ps1`.
3. Fill the IMEI to ThingsBoard access-token mapping.
4. Start the receiver:

```powershell
.\start_teltonika_receiver.ps1
```

The local SQLite database is created as `telemetria.db`. Use `export_teltonika_csv.ps1` to export direct Teltonika records.
