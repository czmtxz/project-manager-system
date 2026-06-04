# Deploy client-collab changes to production server
# Usage:
#   $env:DEPLOY_SSH_KEY = "C:\path\to\private_key"
#   .\tools\deploy_to_server.ps1
#
# Or place key at project root as .ssh_deploy_key (chmod 600 on Linux)

param(
    [string]$Server = "root@36.212.73.151",
    [string]$RemotePath = "/opt/project_manager/project_manager",
    [string]$SshKey = $env:DEPLOY_SSH_KEY,
    [switch]$Quiet
)

function Write-Deploy($msg, $color) {
    if ($Quiet) { return }
    if ($color) { Write-Host $msg -ForegroundColor $color }
    else { Write-Host $msg }
}

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

if (-not $SshKey) {
    $defaultKey = Join-Path $ProjectRoot ".ssh_deploy_key"
    if (Test-Path $defaultKey) { $SshKey = $defaultKey }
}

if (-not $SshKey -or -not (Test-Path $SshKey)) {
    Write-Deploy "ERROR: Set DEPLOY_SSH_KEY or place .ssh_deploy_key in project root." Red
    exit 1
}

$sshOpts = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30")
$scpOpts = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no")

Write-Deploy "==> Testing SSH..."
& ssh @sshOpts $Server "echo OK && hostname" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$coreExplicit = @(
    "app.py", "user_access.py", "project_display.py", "invoice_mgmt.py",
    "auth_utils.py", "client_portal_utils.py", "client_collab_ops.py",
    "client_collab_scope.py", "client_collab_reports.py", "route_extensions.py",
    "project_category_utils.py", "partner_import_utils.py", "ocr_utils.py",
    "report_registry.py", "report_service.py", "report_export.py",
    "reports_routes.py", "report_hub_prefs.py", "report_hub_preview.py",
    "requirements.txt"
)
$autoRootPy = Get-ChildItem -Path $ProjectRoot -Filter "*.py" -File |
    Where-Object { $_.Name -notmatch '^(check_|test_|setup_|update_)' } |
    Select-Object -ExpandProperty Name
$files = ($coreExplicit + $autoRootPy) | Select-Object -Unique

Write-Deploy "==> Uploading core files ($($files.Count))..."
foreach ($f in $files) {
    if (Test-Path $f) {
        & scp @scpOpts $f "${Server}:${RemotePath}/" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Deploy "  $f"
    }
}

Write-Deploy "==> Uploading templates..."
& scp @scpOpts -r "templates" "${Server}:${RemotePath}/" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Deploy "==> Uploading static assets..."
& ssh @sshOpts $Server "mkdir -p ${RemotePath}/static/css" 2>&1 | Out-Null
if (Test-Path "static/css/report_hub.css") {
    & scp @scpOpts "static/css/report_hub.css" "${Server}:${RemotePath}/static/css/" 2>&1 | Out-Null
}

Write-Deploy "==> Uploading migrations and tools..."
& scp @scpOpts -r "migrations" "${Server}:${RemotePath}/" 2>&1 | Out-Null
& ssh @sshOpts $Server "mkdir -p ${RemotePath}/tools" 2>&1 | Out-Null
if (Test-Path "tools/migrate_client_customer_binding.py") {
    & scp @scpOpts "tools/migrate_client_customer_binding.py" "${Server}:${RemotePath}/tools/" 2>&1 | Out-Null
}

Write-Deploy "==> Running migrations on server..."
if (Test-Path "tools/fix_user_roles_on_server.py") {
    & scp @scpOpts "tools/fix_user_roles_on_server.py" "${Server}:${RemotePath}/tools/" 2>&1 | Out-Null
}
$remoteCmd = @"
cd $RemotePath && \
python3 migrations/client_collab_isolation.py 2>/dev/null; \
python3 tools/migrate_client_customer_binding.py 2>/dev/null; \
python3 tools/fix_user_roles_on_server.py 2>/dev/null; \
echo 'Migrations done'
"@
& ssh @sshOpts $Server $remoteCmd 2>&1 | Out-Null

Write-Deploy "==> Restarting service..."
& ssh @sshOpts $Server @"
cd $RemotePath && \
(pgrep -f 'python.*app.py' | head -1) && \
systemctl restart project_manager 2>/dev/null || \
systemctl restart gunicorn 2>/dev/null || \
(pkill -f 'python.*app.py'; sleep 1; nohup python3 app.py >> /var/log/project_manager.log 2>&1 &) || \
echo 'Please restart app manually'
"@ 2>&1 | Out-Null

Write-Deploy "==> Health check..."
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://36.212.73.151:888/login" -UseBasicParsing -TimeoutSec 15
    Write-Deploy "Web login HTTP $($r.StatusCode)" Green
} catch {
    Write-Deploy "Web check failed: $_" Yellow
}

Write-Deploy "Deploy finished." Green
