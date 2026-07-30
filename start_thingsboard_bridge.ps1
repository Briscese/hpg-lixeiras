$ErrorActionPreference = 'Stop'

# Cada IMEI do Traccar e enviado ao seu dispositivo correspondente no ThingsBoard.
$env:TB_MQTT_DEVICES = @{
    '868018073158480' = 'jNyhetB0kVXOtJJsESKG' # FMC150
    '865124071714283' = 'CwiCBw8kNbw1RkG8DjTt' # FMC130
    '863238074508468' = '7kjwB9OXXU7ZLCgK0zGU' # ATC700
    '863251072756898' = 'o6APqlE2ieAZwAYr9wSx' # Novo dispositivo legado
} | ConvertTo-Json -Compress
$env:TB_MQTT_HOST = 'thingsboard.iot8.com.br'
$env:TB_MQTT_PORT = '1883'

# Deve ser igual ao valor configurado em forward.header no traccar.xml.
$env:BRIDGE_SHARED_SECRET = 'fmc150-traccar-bridge-6af476d31d6f4a1aa9a7d093d3d4e7b'

python "$PSScriptRoot\thingsboard_bridge.py"
