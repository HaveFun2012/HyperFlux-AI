<#
Builds HyperFlux and its installer locally, the same way the release workflow does:
icon -> app bundle (PyInstaller) -> smoke test -> installer (Inno Setup) -> release notes.

The version always comes from src\hyperflux\version.py, so a local installer can
never be mislabelled. Output: src\dist\HyperFlux-Setup.exe (+ .sha256, RELEASE-NOTES.md).

Run from anywhere:  powershell -ExecutionPolicy Bypass -File src\packaging\build_release.ps1
#>
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# HyperFlux must be closed: while it runs, Windows locks the files in src\dist.
if (Get-Process -Name HyperFlux -ErrorAction SilentlyContinue) {
    throw "HyperFlux is running. Close it first; its files in src\dist are locked while it is open."
}

$Python = Join-Path $Src "python_embed\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }

$VersionFile = Join-Path $Src "hyperflux\version.py"
$Match = Select-String -LiteralPath $VersionFile -Pattern '__version__ = "([^"]+)"'
if (-not $Match) { throw "Could not read __version__ from $VersionFile." }
$Version = $Match.Matches[0].Groups[1].Value
Write-Host "Building HyperFlux $Version"

$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) was not found. Install it from https://jrsoftware.org/isinfo.php." }

function Invoke-Step($Name, [scriptblock]$Command) {
    Write-Host "== $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE." }
}

Push-Location $Src
try {
    Invoke-Step "Icon" { & $Python packaging\build_icon.py }
    Invoke-Step "App bundle" {
        & $Python -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build packaging\hyperflux.spec
    }
    Invoke-Step "Smoke test" { & dist\HyperFlux\HyperFlux.exe --smoke-test }
    $env:HYPERFLUX_VERSION = $Version
    Invoke-Step "Installer" { & $Iscc /Qp packaging\installer\HyperFlux.iss }
    Invoke-Step "Release notes" { & $Python packaging\release-notes\generate.py --version "v$Version" }
}
finally {
    Pop-Location
}

$Setup = Get-Item (Join-Path $Src "dist\HyperFlux-Setup.exe")
Write-Host ("Done: {0} ({1:N0} MB), version {2}" -f $Setup.FullName, ($Setup.Length / 1MB), $Version)
