$ErrorActionPreference = 'Stop'

# Copy this file to start_teltonika_receiver.ps1 and replace the placeholders.
$env:TB_MQTT_DEVICES = @{
    'ATC700_IMEI' = 'ATC700_THINGSBOARD_ACCESS_TOKEN'
    'TAT141_IMEI' = 'TAT141_THINGSBOARD_ACCESS_TOKEN'
} | ConvertTo-Json -Compress
$env:TELTONIKA_DEVICE_NAMES = @{
    'ATC700_IMEI' = 'ATC700'
    'TAT141_IMEI' = 'TAT141'
} | ConvertTo-Json -Compress
$env:TB_MQTT_HOST = 'thingsboard.iot8.com.br'
$env:TB_MQTT_PORT = '1883'
$env:TELTONIKA_LISTEN_PORT = '29626'

python "$PSScriptRoot\teltonika_receiver.py"
