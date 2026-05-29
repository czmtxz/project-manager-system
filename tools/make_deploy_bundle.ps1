$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
$out = Join-Path $ProjectRoot "deploy_bundle.zip"
if (Test-Path $out) { Remove-Item $out -Force }
$staging = Join-Path $env:TEMP "pm_deploy_$(Get-Date -Format 'yyyyMMddHHmmss')"
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$copy = @(
    "app.py", "auth_utils.py", "client_portal_utils.py", "route_extensions.py",
    "project_category_utils.py", "ocr_utils.py", "requirements.txt"
)
foreach ($f in $copy) {
    Copy-Item $f -Destination $staging
}
Copy-Item templates -Destination (Join-Path $staging "templates") -Recurse
Copy-Item migrations -Destination (Join-Path $staging "migrations") -Recurse
New-Item -ItemType Directory -Force -Path (Join-Path $staging "tools") | Out-Null
Copy-Item tools/migrate_client_customer_binding.py, tools/server_post_deploy.sh, tools/DEPLOY_SERVER.md -Destination (Join-Path $staging "tools")

Compress-Archive -Path "$staging\*" -DestinationPath $out -Force
Remove-Item $staging -Recurse -Force
Write-Host "Created: $out"
Get-Item $out | Select-Object FullName, Length
