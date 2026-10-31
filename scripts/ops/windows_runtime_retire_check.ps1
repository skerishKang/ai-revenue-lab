# Read-only inventory. Run only when explicitly authorized on the target host.
$names = @(
  'PADIEM-Local-AI-OnLogon',
  'PADIEM-Local-AI-Watchdog',
  'PADIEM-COM2-Runtime-Supervisor',
  'PADIEM-COM2-D1-R2-Sync',
  'PADIEM-COM2-Backup'
)
$tasks = foreach ($name in $names) {
  try {
    $found = @(Get-ScheduledTask -TaskName $name -ErrorAction Stop)
    foreach ($task in $found) {
      [pscustomobject]@{ Kind='Task'; Name=$task.TaskName; Location=$task.TaskPath; Status=$task.State }
    }
  } catch {
    [pscustomobject]@{ Kind='Task'; Name=$name; Location='UNKNOWN'; Status='NOT_READ_OR_ABSENT' }
  }
}
$ports = foreach ($port in @(18764,18717,18731)) {
  try {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)
    foreach ($item in $listeners) {
      [pscustomobject]@{ Kind='Port'; Name=$port; Location=$item.LocalAddress; Status='LISTEN' }
    }
  } catch {
    [pscustomobject]@{ Kind='Port'; Name=$port; Location='UNKNOWN'; Status='NOT_READ_OR_ABSENT' }
  }
}
@($tasks) + @($ports) | Format-Table -AutoSize
