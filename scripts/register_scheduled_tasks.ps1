<#
Регистрирует три задачи в Планировщике заданий Windows для непрерывного сбора данных:
  - evcharge-evse-status : каждые 15 минут
  - evcharge-evse-data   : раз в сутки (03:00)
  - evcharge-weather     : раз в сутки (03:30)

Запускать один раз от имени администратора:
  powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1
#>

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

function Register-IngestionTask {
    param(
        [string]$Name,
        [string]$Module,
        [string]$Schedule,   # MINUTE | DAILY
        [int]$Interval,      # для MINUTE — период в минутах; для DAILY игнорируется
        [string]$StartTime  # для DAILY, формат HH:mm
    )

    $action = New-ScheduledTaskAction -Execute $python -Argument "-m $Module" -WorkingDirectory $projectRoot

    if ($Schedule -eq "MINUTE") {
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $Interval) -RepetitionDuration (New-TimeSpan -Days 3650)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $StartTime
    }

    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output "Registered: $Name"
}

Register-IngestionTask -Name "evcharge-evse-status" -Module "src.ingestion.evse_status" -Schedule "MINUTE" -Interval 15
Register-IngestionTask -Name "evcharge-evse-data"   -Module "src.ingestion.evse_data"   -Schedule "DAILY" -StartTime "03:00"
Register-IngestionTask -Name "evcharge-weather"     -Module "src.ingestion.weather"     -Schedule "DAILY" -StartTime "03:30"
