# Stop the dashboard and remove it from login startup on Windows.
$ErrorActionPreference = "SilentlyContinue"

$Startup  = [Environment]::GetFolderPath("Startup")
$Launcher = Join-Path $Startup "WorldCup2026Dashboard.vbs"

if (Test-Path $Launcher) {
  Remove-Item $Launcher -Force
  Write-Host "==> Removed $Launcher — the dashboard will no longer start at login."
} else {
  Write-Host "==> Nothing to remove (Startup launcher not found)."
}

# Best-effort: stop the running server (pythonw running run.py).
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'run\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "==> Done."
