# Deploy client-collab changes to production server
# Usage:
#   $env:DEPLOY_SSH_KEY = "C:\path\to\private_key"
#   .\tools\deploy_to_server.ps1
#
# Or place key at project root as .ssh_deploy_key (chmod 600 on Linux)

param(
    [string]$Server = "root@36.212.73.151",
    [string]$RemotePath = "/opt/project_manager/project_manager",
    [string]$SshKey = $env:DEPLOY_SSH_KEY
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

if (-not $SshKey) {
    $defaultKey = Join-Path $ProjectRoot ".ssh_deploy_key"
    if (Test-Path $defaultKey) { $SshKey = $defaultKey }
}

if (-not $SshKey -or -not (Test-Path $SshKey)) {
    Write-Host "ERROR: Set DEPLOY_SSH_KEY or place .ssh_deploy_key in project root." -ForegroundColor Red
    exit 1
}

$sshOpts = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30")
$scpOpts = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no")

Write-Host "==> Testing SSH..."
& ssh @sshOpts $Server "echo OK && hostname"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$files = @(
    "app.py",
    "auth_utils.py",
    "client_portal_utils.py",
    "client_collab_ops.py",
    "client_collab_scope.py",
    "route_extensions.py",
    "project_category_utils.py",
    "ocr_utils.py",
    "report_registry.py",
    "report_service.py",
    "report_export.py",
    "reports_routes.py",
    "report_hub_prefs.py",
    "report_hub_preview.py",
    "requirements.txt"
)

Write-Host "==> Uploading core files..."
foreach ($f in $files) {
    if (Test-Path $f) {
        & scp @scpOpts $f "${Server}:${RemotePath}/"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "  $f"
    }
}

Write-Host "==> Uploading templates..."
& scp @scpOpts -r "templates" "${Server}:${RemotePath}/"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Uploading static assets..."
& ssh @sshOpts $Server "mkdir -p ${RemotePath}/static/css"
& scp @scpOpts "static/css/report_hub.css" "${Server}:${RemotePath}/static/css/"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Uploading migrations and tools..."
& scp @scpOpts -r "migrations" "${Server}:${RemotePath}/"
& scp @scpOpts "tools/migrate_client_customer_binding.py" "${Server}:${RemotePath}/tools/" 2>$null
& ssh @sshOpts $Server "mkdir -p ${RemotePath}/tools"
& scp @scpOpts "tools/migrate_client_customer_binding.py" "${Server}:${RemotePath}/tools/"
& scp @scpOpts "migrations/client_collab_isolation.py" "${Server}:${RemotePath}/migrations/"

Write-Host "==> Running migrations on server..."
$remoteCmd = @"
cd $RemotePath && \
python3 migrations/client_collab_isolation.py && \
python3 tools/migrate_client_customer_binding.py && \
echo 'Migrations done'
"@
& ssh @sshOpts $Server $remoteCmd

Write-Host "==> Restarting service..."
& ssh @sshOpts $Server @"
cd $RemotePath && \
(pgrep -f 'python.*app.py' | head -1) && \
systemctl restart project_manager 2>/dev/null || \
systemctl restart gunicorn 2>/dev/null || \
(pkill -f 'python.*app.py'; sleep 1; nohup python3 app.py >> /var/log/project_manager.log 2>&1 &) || \
echo 'Please restart app manually'
"@

Write-Host "==> Health check..."
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://36.212.73.151:888/login" -UseBasicParsing -TimeoutSec 15
    Write-Host "Web login HTTP $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Web check failed: $_" -ForegroundColor Yellow
}

Write-Host "Deploy finished." -ForegroundColor Green
