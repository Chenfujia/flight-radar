$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "Flight Radar"
$startScript = Join-Path $projectRoot "start.ps1"
$taskArguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $startScript + '"'

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Personal Flight Radar" -Force | Out-Null
Write-Host "Windows 任务已安装：$taskName"
