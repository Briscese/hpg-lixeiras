$ErrorActionPreference = 'Stop'

$env:TB_MQTT_DEVICES = @{
    '863238074508468' = '7kjwB9OXXU7ZLCgK0zGU' # ATC700
    '863251072756898' = 'o6APqlE2ieAZwAYr9wSx' # TAT141
} | ConvertTo-Json -Compress
$env:TELTONIKA_DEVICE_NAMES = @{
    '863238074508468' = 'ATC700'
    '863251072756898' = 'TAT141'
} | ConvertTo-Json -Compress
$env:TB_MQTT_HOST = 'thingsboard.iot8.com.br'
$env:TB_MQTT_PORT = '1883'
$env:TELTONIKA_LISTEN_PORT = '29626'

python "$PSScriptRoot\teltonika_receiver.py"
