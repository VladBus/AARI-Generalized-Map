# Registers one portable Task Scheduler task with three repeating time windows.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$bat = Join-Path $projectRoot 'run_aari_generalized_map.bat'
if (-not (Test-Path -LiteralPath $bat)) { throw "Не найден файл запуска: $bat" }

$taskName = 'AARI-Generalized-Map'
$userId = "$env:USERDOMAIN\$env:USERNAME"
$today = Get-Date -Format 'yyyy-MM-dd'
$command = "$env:WINDIR\System32\cmd.exe"
$arguments = '/d /c "' + $bat + '" --stage auto --execute'

# One task and one BAT. Triggers repeat every five minutes while source files
# are being finalized; each individual process then exits.
$xml = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Автоматизация рассылки и публикации Обобщённой карты ААНИИ</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger><StartBoundary>${today}T11:00:00</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT50M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Wednesday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
    <CalendarTrigger><StartBoundary>${today}T14:00:00</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT50M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Wednesday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
    <CalendarTrigger><StartBoundary>${today}T14:00:00</StartBoundary><Enabled>true</Enabled><Repetition><Interval>PT5M</Interval><Duration>PT50M</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><ScheduleByWeek><DaysOfWeek><Thursday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek></CalendarTrigger>
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
Write-Host '  Среда: 11:00–11:50 (проверка old_shore до 12:00)'
Write-Host '  Среда: 14:00–14:50 (основные копии и 5 писем)'
Write-Host '  Четверг: 14:00–14:50 (LVP и сайт за прошлую неделю)'
Write-Host 'Запуски повторяются раз в 5 минут, но все используют один BAT. Требуется вход в Windows под учётной записью с доступом к сетевым ресурсам.'
