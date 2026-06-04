# 安装 git post-commit 钩子：每次本地 commit 后自动部署
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$hooksDir = Join-Path $ProjectRoot ".git\hooks"
$hookPath = Join-Path $hooksDir "post-commit"

if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
    Write-Host "Not a git repository." -ForegroundColor Red
    exit 1
}

$hookContent = @'
#!/bin/sh
# Auto push + deploy after commit (Windows: PowerShell)
ROOT="$(git rev-parse --show-toplevel)"
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "$ROOT/tools/auto_git_push_deploy.ps1" -Quiet
exit 0
'@

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
Set-Content -Path $hookPath -Value $hookContent -Encoding UTF8 -NoNewline
Write-Host "Installed: $hookPath" -ForegroundColor Green
Write-Host "Each git commit will run auto_git_push_deploy.ps1 (push + deploy if SSH key present)."
