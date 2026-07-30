# hpg-lixeiras

Rastreamento GPS de lixeiras.

## Teltonika to ThingsBoard bridge

Receives JSON positions forwarded by Traccar, stores valid GNSS positions in SQLite, and publishes telemetry to ThingsBoard MQTT.

## Local setup

1. Copy `start_thingsboard_bridge.example.ps1` to `start_thingsboard_bridge.ps1`.
2. Fill the IMEI to ThingsBoard access-token mapping and integration secret.
3. Configure Traccar using `traccar-forwarding.example.xml` with the same secret.
4. Start the bridge:

```powershell
.\start_thingsboard_bridge.ps1
```

The local SQLite database is created as `telemetria.db`. Use the CSV export script to create an export of saved records.
