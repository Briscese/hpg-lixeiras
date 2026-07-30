$ErrorActionPreference = 'Stop'

# Copy this file to start_thingsboard_bridge.ps1 and replace the placeholders.
$env:TB_MQTT_DEVICES = @{
    'DEVICE_IMEI_1' = 'THINGSBOARD_ACCESS_TOKEN_1'
    'DEVICE_IMEI_2' = 'THINGSBOARD_ACCESS_TOKEN_2'
} | ConvertTo-Json -Compress
$env:TB_MQTT_HOST = 'thingsboard.iot8.com.br'
$env:TB_MQTT_PORT = '1883'

# Must match the X-Bridge-Key configured in Traccar forwarding.
$env:BRIDGE_SHARED_SECRET = 'REPLACE_WITH_A_LONG_RANDOM_SECRET'

python "$PSScriptRoot\thingsboard_bridge.py"
