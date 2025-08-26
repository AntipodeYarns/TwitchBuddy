param(
    [string]$DestRoot = "backups"
)

# Create a timestamped folder and copy DBs and twitch_config.json into it, then zip
$ts = (Get-Date).ToString('yyyyMMdd-HHmmss')
$dest = Join-Path -Path $DestRoot -ChildPath $ts
New-Item -ItemType Directory -Path $dest -Force | Out-Null

Get-ChildItem -Path . -Filter "*.db" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $dest -Force
}

if (Test-Path .\twitch_config.json) {
    Copy-Item -Path .\twitch_config.json -Destination $dest -Force
}

# compress
$zip = Join-Path -Path $DestRoot -ChildPath ("project-snapshot-$ts.zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dest -DestinationPath $zip
Write-Host "Backup written to $zip"
