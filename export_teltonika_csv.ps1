$ErrorActionPreference = 'Stop'

$database = Join-Path $PSScriptRoot 'telemetria.db'
$output = Join-Path $PSScriptRoot ("teltonika-{0}.csv" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

if (-not (Test-Path -LiteralPath $database)) {
    throw "Banco local nao encontrado: $database"
}

python -c "import csv, sqlite3, sys; db, output = sys.argv[1:]; connection = sqlite3.connect(db); cursor = connection.execute('SELECT * FROM teltonika_records ORDER BY device_time_ms'); writer = csv.writer(open(output, 'w', newline='', encoding='utf-8-sig')); writer.writerow([column[0] for column in cursor.description]); writer.writerows(cursor); connection.close()" $database $output

Write-Host "CSV criado: $output"
