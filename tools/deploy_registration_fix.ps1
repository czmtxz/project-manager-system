# 仅部署客户门户注册修复（3 个文件）
param(
    [string]$Server = "root@36.212.73.151",
    [string]$RemotePath = "/opt/project_manager/project_manager",
    [string]$SshKey = $env:DEPLOY_SSH_KEY
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$defaultKey = Join-Path $Root ".ssh_deploy_key"
if (-not $SshKey -and (Test-Path $defaultKey)) { $SshKey = $defaultKey }
if (-not $SshKey -or -not (Test-Path -LiteralPath $SshKey)) {
    Write-Host "未找到 SSH 私钥。请任选其一：" -ForegroundColor Red
    Write-Host "  1) 将密钥保存为: $defaultKey"
    Write-Host "  2) `$env:DEPLOY_SSH_KEY = 'C:\path\to\your_key'"
    Write-Host "  3) 使用宝塔上传 deploy_bundle.zip 后执行 server_post_deploy.sh"
    exit 1
}
$ssh = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30")
$scp = @("-i", $SshKey, "-o", "StrictHostKeyChecking=no")
& ssh @ssh $Server "echo SSH_OK"
foreach ($f in @("app.py", "client_portal_utils.py")) {
    & scp @scp $f "${Server}:${RemotePath}/"
    Write-Host "Uploaded $f"
}
& scp @scp "templates/portal_register.html" "${Server}:${RemotePath}/templates/"
Write-Host "Uploaded portal_register.html"
& ssh @ssh $Server "cd $RemotePath && (systemctl restart project_manager 2>/dev/null || systemctl restart gunicorn 2>/dev/null || (pkill -f 'python.*app.py'; sleep 1; cd $RemotePath && nohup python3 app.py >>/var/log/project_manager.log 2>&1 &))"
Start-Sleep 2
$r = Invoke-WebRequest -Uri "http://36.212.73.151:888/portal/register" -UseBasicParsing
if ($r.Content -match 'name="contact_name"') { Write-Host "Server fix verified: contact_name" -ForegroundColor Green }
else { Write-Host "Server may still be old - check manually" -ForegroundColor Yellow }
