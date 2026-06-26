param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "Argos Silent Mode",
    [string]$PythonExe = "python",
    [string]$UvicornModule = "uvicorn",
    [string]$AppModule = "main:app",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Uninstall,
    [switch]$Status
)

$ErrorActionPreference = "Stop"

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Scheduled task not installed: $TaskName"
        exit 0
    }

    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Scheduled task: $TaskName"
    Write-Host "State: $($task.State)"
    Write-Host "Last run: $($info.LastRunTime)"
    Write-Host "Last result: $($info.LastTaskResult)"
    Write-Host "Next run: $($info.NextRunTime)"
    exit 0
}

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Scheduled task already absent: $TaskName"
        exit 0
    }

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Uninstalled scheduled task: $TaskName"
    exit 0
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "$UvicornModule $AppModule --host $Host --port $Port" -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel LeastPrivilege
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Installed scheduled task: $TaskName"
Write-Host "It will start Argos at user logon; silent mode must still be enabled in .env."
Write-Host "Check status: powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Status"
Write-Host "Uninstall: powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Uninstall"
