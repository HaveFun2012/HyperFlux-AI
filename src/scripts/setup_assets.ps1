[CmdletBinding()]
param(
    [string]$PythonVersion = "3.14.8",
    [ValidateSet("standard", "nocuda", "oldpc")]
    [string]$KoboldVariant = "standard",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# Runtime assets live in src\, one level above this scripts\ folder.
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PythonDirectory = Join-Path $ProjectRoot "python_embed"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
$ModelPath = Join-Path $ProjectRoot "model.gguf"
$KoboldPath = Join-Path $ProjectRoot "koboldcpp.exe"

function Get-Sha256($Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-Gguf($Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    $stream = [IO.File]::OpenRead($Path)
    try {
        $header = New-Object byte[] 4
        $length = $stream.Read($header, 0, $header.Length)
        return $length -eq 4 -and [Text.Encoding]::ASCII.GetString($header) -eq "GGUF"
    }
    finally {
        $stream.Dispose()
    }
}

function Invoke-VerifiedDownload($Uri, $Destination, $ExpectedSha256, $ExpectedSize) {
    $temporaryPath = "$Destination.download"
    try {
        Write-Host "Downloading $([IO.Path]::GetFileName($Destination))..."
        Invoke-WebRequest -Uri $Uri -OutFile $temporaryPath -UseBasicParsing
        if ($ExpectedSize -gt 0 -and (Get-Item -LiteralPath $temporaryPath).Length -ne $ExpectedSize) {
            throw "Downloaded file size does not match the release metadata."
        }
        if ($ExpectedSha256) {
            $actualHash = Get-Sha256 $temporaryPath
            if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
                throw "SHA-256 verification failed for $([IO.Path]::GetFileName($Destination))."
            }
        }
        Move-Item -LiteralPath $temporaryPath -Destination $Destination -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Get-KoboldAsset {
    $apiUrl = "https://api.github.com/repos/LostRuins/koboldcpp/releases/latest"
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "HyperFlux-Asset-Setup"
    }
    $assetName = switch ($KoboldVariant) {
        "standard" { "koboldcpp.exe" }
        "nocuda" { "koboldcpp-nocuda.exe" }
        "oldpc" { "koboldcpp-oldpc.exe" }
    }
    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    if (-not $asset) {
        throw "The official KoboldCpp release $($release.tag_name) has no $assetName asset."
    }
    $expectedHash = ""
    if ($asset.digest -match "^sha256:(?<hash>[0-9a-fA-F]{64})$") {
        $expectedHash = $Matches.hash
    }
    Invoke-VerifiedDownload $asset.browser_download_url $KoboldPath $expectedHash $asset.size
    Write-Host "Installed official KoboldCpp release $($release.tag_name) ($assetName)."
}

function Enable-EmbeddedSitePackages($RuntimeDirectory) {
    $pthFile = Get-ChildItem -LiteralPath $RuntimeDirectory -Filter "python*._pth" |
        Select-Object -First 1
    if (-not $pthFile) {
        throw "The downloaded Python runtime has no python*._pth configuration file."
    }
    $contents = [IO.File]::ReadAllText($pthFile.FullName)
    if ($contents -notmatch "(?m)^import site\s*$") {
        $contents = [regex]::Replace($contents, "(?m)^#\s*import site\s*$", "import site")
    }
    if ($contents -notmatch "(?m)^\.\.\s*$") {
        $contents = [regex]::Replace($contents, "\s*$", "") +
            [Environment]::NewLine + ".." + [Environment]::NewLine
    }
    [IO.File]::WriteAllText($pthFile.FullName, $contents)
}

function Install-PythonRuntime {
    $pythonExe = Join-Path $PythonDirectory "python.exe"
    $temporaryRoot = Join-Path $env:TEMP ("HyperFlux-setup-" + [guid]::NewGuid().ToString("N"))
    $archivePath = Join-Path $temporaryRoot "python-embed.zip"
    $stagingDirectory = Join-Path $temporaryRoot "python_embed"
    $pipBootstrap = Join-Path $temporaryRoot "get-pip.py"
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null

    try {
        if ((Test-Path -LiteralPath $PythonDirectory) -and -not (Test-Path -LiteralPath $pythonExe)) {
            throw "python_embed exists but is incomplete. Preserve or rename that folder, then rerun setup."
        }
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            $archiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
            Write-Host "Downloading the official Python $PythonVersion embeddable runtime..."
            Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
            Expand-Archive -LiteralPath $archivePath -DestinationPath $stagingDirectory
            if (-not (Test-Path -LiteralPath (Join-Path $stagingDirectory "python.exe"))) {
                throw "The Python embeddable archive did not contain python.exe."
            }
            Enable-EmbeddedSitePackages $stagingDirectory
            $pythonExe = Join-Path $stagingDirectory "python.exe"
        }
        else {
            Write-Host "Using the existing embedded Python runtime."
            Enable-EmbeddedSitePackages $PythonDirectory
        }

        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" `
            -OutFile $pipBootstrap -UseBasicParsing
        & $pythonExe $pipBootstrap --disable-pip-version-check --no-warn-script-location
        if ($LASTEXITCODE -ne 0) {
            throw "pip bootstrap failed with exit code $LASTEXITCODE."
        }
        & $pythonExe -m pip install --disable-pip-version-check --no-warn-script-location -r $RequirementsFile
        if ($LASTEXITCODE -ne 0) {
            throw "Python dependency installation failed with exit code $LASTEXITCODE."
        }

        if ($stagingDirectory -and (Test-Path -LiteralPath $stagingDirectory)) {
            Move-Item -LiteralPath $stagingDirectory -Destination $PythonDirectory
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryRoot) {
            Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $RequirementsFile)) {
    throw "requirements.txt is missing from '$ProjectRoot'."
}

if (-not (Test-Gguf $ModelPath)) {
    throw "A valid GGUF model is required at '$ModelPath'. Setup does not download or substitute model files."
}

Install-PythonRuntime

if ((Test-Path -LiteralPath $KoboldPath) -and -not $Force) {
    Write-Host "Keeping existing koboldcpp.exe. Use -Force to replace it with the latest official release."
}
else {
    Get-KoboldAsset
}

Write-Host "Keeping the existing GGUF model; setup never replaces model.gguf."

Write-Host "HyperFlux runtime setup is complete."
