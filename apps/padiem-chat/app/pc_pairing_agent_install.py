"""The one agent-install sequence every PowerShell install lane shares (#5573).

The double-click program (``scripts/pc_pairing/connect-exe/PadiemPcConnect.cs``)
runs a measured sequence, and both PowerShell lanes must run the same one. On
the tagged Windows agent of 2026-10-28 ``-fullinstall`` exited 0 and registered
nothing while ``-install`` registered the service from the folder it ran from -
so the copy into the product's own folder under Program Files is the lane's
job, never the agent switch's, and the service is registered from that durable
folder, started from it, and then read back for its status.

The constants and the PowerShell block below are the single place both lanes
read that sequence from: the server-rendered install script embeds
:func:`render_agent_install_block` when its template is built, the wrapper
script ``scripts/pc_pairing/install-padiem-pc.ps1`` embeds the same block
verbatim, and the tests refuse a copy that drifts - the same refuse-on-drift
contract the .exe build pins with its seed.
"""
from __future__ import annotations

#: The one service the agent registers under. A re-run updates this one
#: service; a lane that registers a second service is wrong.
AGENT_SERVICE_NAME = "Mesh Agent"
#: Where Windows records that service. The ImagePath value under this key is
#: what an update stops the old agent through, whatever folder it came from.
AGENT_SERVICE_REGISTRY_KEY = "SYSTEM\\CurrentControlSet\\Services\\Mesh Agent"
AGENT_FILE_NAME = "MeshAgent.exe"
#: The durable folder under the real Program Files - not Temp, and not the
#: old "%ProgramFiles(x86)%\\Mesh Services" default: ``-install`` leaves the
#: executing folder in the service record, so a temp folder would become a
#: service that cannot start once that folder is cleaned up.
AGENT_DURABLE_FOLDER = "PADIEM"
#: Measured, not assumed (PadiemPcConnect.cs records the run): this agent
#: build's ``-fullinstall`` exited 0 and registered nothing.
AGENT_INSTALL_SWITCH = "-install"


_AGENT_INSTALL_BLOCK = r"""# ---- the agent install sequence the double-click program runs ----
# Measured on the tagged Windows agent of 2026-10-28 (PadiemPcConnect.cs):
# -fullinstall exited 0 and registered nothing, while -install registered the
# service from the folder it ran from. So the copy into the product's own
# folder under Program Files is this script's job, and -install runs from
# there - never -fullinstall, never out of a temp folder.
$PadiemAgentServiceName = "Mesh Agent"
# The durable folder lives under the real Program Files. A validation-only
# run on a host without it (CI Linux, pwsh) must reach its own refusal, not
# die here: the install walk below only runs on a Windows PC that has it.
$PadiemAgentDurableDir = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles "PADIEM" } else { $null }
$PadiemAgentDurableExe = if ($PadiemAgentDurableDir) { Join-Path $PadiemAgentDurableDir "MeshAgent.exe" } else { $null }

function Install-PadiemAgentService {
  # Stops an existing service through the binary its own record names, copies
  # the downloaded agent into the durable folder, registers the same single
  # service from there with -install, starts it, and answers whether the
  # service is registered afterwards. Never registers a second service: the
  # name is the one constant above, so a re-run updates in place.
  param([string] $SourceExe, [string] $AgentName)
  $record = "HKLM:\SYSTEM\CurrentControlSet\Services\" + $PadiemAgentServiceName
  $item = Get-ItemProperty -Path $record -Name ImagePath -ErrorAction SilentlyContinue
  $registered = $null
  if ($item) { $registered = ([string] $item.ImagePath).Trim() }
  if ($registered) {
    if ($registered.StartsWith('"')) {
      $closing = $registered.IndexOf('"', 1)
      $registered = if ($closing -gt 1) { $registered.Substring(1, $closing - 1) } else { $null }
    } else {
      $space = $registered.IndexOf(' ')
      $registered = if ($space -ge 0) { $registered.Substring(0, $space) } else { $registered }
    }
  }
  if ($registered -and (Test-Path -LiteralPath $registered)) {
    # The stop is asked of the agent binary itself, the way the double-click
    # program does it; a refusal here is not a failure - the copy below
    # retries over a file a still-running agent holds.
    try {
      Start-Process -FilePath $registered -ArgumentList "-stop" -Wait -WindowStyle Hidden | Out-Null
    } catch { }
  }
  New-Item -ItemType Directory -Path $PadiemAgentDurableDir -Force | Out-Null
  $copied = $false
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try {
      Copy-Item -LiteralPath $SourceExe -Destination $PadiemAgentDurableExe -Force
      $copied = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }
  if (-not $copied) { return $false }
  try {
    $installed = Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList @("-install", ('--agentName="' + $AgentName + '"')) -Wait -PassThru -WindowStyle Hidden
  } catch {
    return $false
  }
  if (-not $installed -or $installed.ExitCode -ne 0) { return $false }
  # -install registers; it does not launch. The start is what makes a fresh PC
  # answer the server's first call instead of waiting for the next restart.
  try {
    Start-Process -FilePath $PadiemAgentDurableExe -ArgumentList "-start" -Wait -WindowStyle Hidden | Out-Null
  } catch { }
  $service = Get-Service -Name $PadiemAgentServiceName -ErrorAction SilentlyContinue
  return ($null -ne $service)
}
"""


def render_agent_install_block() -> str:
    """The self-contained PowerShell block both .ps1 lanes embed verbatim.

    The inputs are the two values every lane already has - the downloaded
    installer path and the agent name the server pairs on. The block stops an
    existing service through the binary its own record names, copies the agent
    into the durable folder, registers the one service from there with
    ``-install``, starts it, and answers whether the service is registered
    afterwards. Nothing here reads or writes a pairing secret.
    """
    return _AGENT_INSTALL_BLOCK
