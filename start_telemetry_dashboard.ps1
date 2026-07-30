$ErrorActionPreference = 'Stop'
$env:TELEMETRY_DASHBOARD_HOST = '127.0.0.1'
$env:TELEMETRY_DASHBOARD_PORT = '8787'

python "$PSScriptRoot\telemetry_dashboard.py"
