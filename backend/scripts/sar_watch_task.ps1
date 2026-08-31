<#
.SYNOPSIS
    One scheduled check for a post-event Sentinel-1 scene.

.DESCRIPTION
    Thin wrapper around watch_for_post_event_sar.py, intended to be driven
    by a Windows Scheduled Task rather than run by hand.

    Why a scheduled task rather than a long-running poller: waiting for a
    Sentinel-1 pass is a multi-day job. The satellite flies a fixed 12-day
    repeat, and the RTC product is published 1-3 days after acquisition.
    No interactive session or background process reliably lives that long,
    and two earlier attempts here died -- once when the container it ran
    inside was restarted, once when the environment stopped the background
    task. A scheduled task is the only thing on this machine that
    genuinely survives reboots, container restarts and closed sessions.

    Each run appends a timestamped result to the log. When a post-event
    scene finally appears, it also writes a marker file containing the
    exact map_flood_extent.py command to run -- so the outcome is a file
    you can find later, not a notification you had to be present for.

    Deliberately does NOT run the flood mapping itself. That reads two
    large rasters over the network and writes a GeoTIFF; doing it
    unattended from a scheduler, possibly while the Docker stack is down,
    would be a poor trade for the few seconds it takes to run knowingly.

.PARAMETER RepoRoot
    Project root (the directory containing backend/).

.PARAMETER MinX
    Bounding box west edge, EPSG:4326. (MinY/MaxX/MaxY likewise.)

.PARAMETER EventTime
    ISO event time, e.g. 2026-08-26T09:00

.EXAMPLE
    .\sar_watch_task.ps1 -RepoRoot "E:\...\FloodHUBnepal-main" `
        -MinX 85.28 -MinY 28.10 -MaxX 85.45 -MaxY 28.32 -EventTime 2026-08-26T09:00
#>
param(
    [Parameter(Mandatory = $true)][string]   $RepoRoot,
    # Four separate scalars rather than a [double[]]: when powershell.exe
    # is launched with -File (which is how Scheduled Tasks run a script),
    # every argument arrives as a STRING, so "85.28,28.1,85.45,28.32"
    # fails to coerce to double[] and the script dies during parameter
    # binding -- before it can log anything. That failure mode is silent
    # from the scheduler's point of view: the task reports a non-zero
    # result and writes no output at all, which is exactly how it
    # presented here.
    [Parameter(Mandatory = $true)][double] $MinX,
    [Parameter(Mandatory = $true)][double] $MinY,
    [Parameter(Mandatory = $true)][double] $MaxX,
    [Parameter(Mandatory = $true)][double] $MaxY,
    [Parameter(Mandatory = $true)][string]   $EventTime,
    [string] $LogFile   = "$env:USERPROFILE\floodhub_sar_watch.log",
    [string] $FoundFile = "$env:USERPROFILE\floodhub_sar_FOUND.txt",
    # Absolute interpreter path. A Scheduled Task does not inherit the
    # interactive PATH -- especially with -NoProfile -- so a bare
    # "python" fails to resolve. Register the task with the full path;
    # the "python" default is only for running this by hand.
    [string] $PythonExe = "python"
)

$ErrorActionPreference = 'Continue'
$script = Join-Path $RepoRoot 'backend\scripts\watch_for_post_event_sar.py'
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

if (-not (Test-Path $script)) {
    "[$stamp] ERROR: watcher script not found at $script" | Add-Content $LogFile
    exit 2
}

# Once found, stop re-reporting: leave the marker as the durable record
# and keep the log quiet rather than appending the same hit indefinitely.
if (Test-Path $FoundFile) {
    "[$stamp] already found previously; see $FoundFile" | Add-Content $LogFile
    exit 0
}

if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    "[$stamp] ERROR: python not found at '$PythonExe' (PATH is not inherited by Scheduled Tasks; pass -PythonExe with an absolute path)" | Add-Content $LogFile
    exit 3
}

$output   = & $PythonExe -u $script --bbox $MinX $MinY $MaxX $MaxY --event $EventTime 2>&1
$exitCode = $LASTEXITCODE

"[$stamp] exit=$exitCode" | Add-Content $LogFile
$output | ForEach-Object { "    $_" } | Add-Content $LogFile

if ($exitCode -eq 0) {
    # exit 0 from the watcher means a post-event scene is available and it
    # printed the correctly-paired map_flood_extent.py invocation.
    @(
        "POST-EVENT SENTINEL-1 SCENE AVAILABLE"
        "Detected: $stamp"
        ""
        ($output -join "`r`n")
        ""
        "Run the command above inside the backend container:"
        "  cd `"$RepoRoot`""
        "  docker cp backend\scripts\map_flood_extent.py floodhubnepal-main-backend-1:/app/map_flood_extent.py"
        "  docker compose exec -T backend python /app/map_flood_extent.py ..."
    ) | Set-Content $FoundFile -Encoding UTF8

    "[$stamp] *** FOUND -- wrote $FoundFile ***" | Add-Content $LogFile
}

exit $exitCode
