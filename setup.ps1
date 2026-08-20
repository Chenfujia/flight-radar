$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python，请安装 Python 3.11 或更高版本。"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uvScript = Join-Path $env:APPDATA "Python\Python311\Scripts\uv.exe"
    if (Test-Path -LiteralPath $uvScript) {
        $env:Path = "$(Split-Path $uvScript);$env:Path"
    } else {
        python -m pip install --user uv
        $env:Path = "$(Join-Path $env:APPDATA 'Python\Python311\Scripts');$env:Path"
    }
}

uv sync
New-Item -ItemType Directory -Force -Path ".\data\backups", ".\logs" | Out-Null
if (-not (Test-Path -LiteralPath ".\config\radar.toml")) {
    uv run flight-radar init
}
uv run flight-radar doctor
Write-Host "安装完成。请设置 PUSHPLUS_TOKEN 后运行 install-task.ps1。"
