# Register one portable Task Scheduler task with four triggers and a single BAT launcher.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$bat = Join-Path $projectRoot 'run_aari_generalized_map.bat'
if (-not (Test-Path -LiteralPath $bat)) { throw "Не найден файл запуска: $bat" }

function Get-NextStartBoundary {
    param(
        [System.DayOfWeek]$Day,
        [string]$Time
    )
    $now = Get-Date
    $offset = (([int]$Day - [int]$now.DayOfWeek + 7) % 7)
    $candidate = $now.Date.AddDays($offset).Add([TimeSpan]::Parse($Time))
    if ($candidate -le $now) { $candidate = $candidate.AddDays(7) }
    return $candidate.ToString("yyyy-MM-dd'T'HH:mm:ss")
}

$taskName = 'AARI-Generalized-Map'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$command = "$env:WINDIR\System32\cmd.exe"
$arguments = '/d /c "' + $bat + '" --stage auto --execute'
$wed11Boundary = Get-NextStartBoundary -Day ([System.DayOfWeek]::Wednesday) -Time '11:00:00'
$wed14Boundary = Get-NextStartBoundary -Day ([System.DayOfWeek]::Wednesday) -Time '14:00:00'
$wed15Boundary = Get-NextStartBoundary -Day ([System.DayOfWeek]::Wednesday) -Time '15:00:00'
$thu14Boundary = Get-NextStartBoundary -Day ([System.DayOfWeek]::Thursday) -Time '14:00:00'

# One task, one action, one BAT. Repeated windows use short-lived invocations.
# Duration PT55M permits launches at :00, :05, ... :50.
$xml = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Автоматизация рассылки и публикации Обобщённой карты ААНИИ</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger><StartBoundary>${wed11Boundary}</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT55M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Wednesday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
    <CalendarTrigger><StartBoundary>${wed14Boundary}</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT55M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Wednesday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
    <CalendarTrigger><StartBoundary>${thu14Boundary}</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT55M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Thursday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
    <CalendarTrigger><StartBoundary>${wed15Boundary}</StartBoundary><Enabled>true</Enabled><ScheduleByWeek><DaysOfWeek><Wednesday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>${userId}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit><Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>${command}</Command><Arguments>${arguments}</Arguments><WorkingDirectory>${projectRoot}</WorkingDirectory></Exec></Actions>
</Task>
"@
$xml = $xml.Replace('${', '$' + '{')
Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
Write-Host "Задача '$taskName' зарегистрирована:"
Write-Host '  Среда: 11:00–11:50 (old_shore также повторно проверяется в 14:00–14:50)'
Write-Host '  Среда: 14:00–14:50 (основные копии и пять продуктовых писем)'
Write-Host '  Среда: 15:00 (еженедельный статусный отчёт и создание папки следующего выпуска)'
Write-Host '  Четверг: 14:00–14:50 (LVP и сайт за предыдущую неделю)'
Write-Host 'Все триггеры используют один BAT. Для сетевых ресурсов требуется вход в Windows под учётной записью с соответствующими правами.'
