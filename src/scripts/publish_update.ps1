<#
Publishes a HyperFlux update in one go:
  1. checks your changes are committed
  2. asks for the new version number (e.g. 1.1.0)
  3. makes sure its patch notes exist (src\packaging\release-notes\versions\v<version>.md);
     if not, creates the file, opens it, and stops so you can write them
  4. runs the tests
  5. sets the version in src\hyperflux\version.py, commits, tags v<version>, and pushes
GitHub then builds the installer (about 10 minutes) and saves it as a DRAFT release.
Nobody gets the update until you open the draft on GitHub and click Publish.
#>
$ErrorActionPreference = "Continue"  # git and python print to stderr; exit codes are checked instead
function Fail($message) { Write-Host "`n$message" -ForegroundColor Red; exit 1 }

$Root = (& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null)
if (-not $Root) { Fail "This folder is not a git repository." }
Set-Location $Root
$Repo = "HaveFun2012/HyperFlux-AI"
$VersionFile = "src\hyperflux\version.py"

if (& git status --porcelain) {
    & git status --short
    Fail "Commit (or undo) your changes first, so the release contains exactly what you tested."
}
$Branch = (& git branch --show-current)
if (-not $Branch) { Fail "Check out a branch first (you are not on one)." }

$Current = (Select-String -Path $VersionFile -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$parts = $Current.Split(".") | ForEach-Object { [int]$_ }
$suggested = "{0}.{1}.0" -f $parts[0], ($parts[1] + 1)
Write-Host "Current version: $Current"
$Version = Read-Host "New version [$suggested]"
if (-not $Version) { $Version = $suggested }
$Version = $Version.TrimStart("v")
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "Use a version like 1.1.0." }
if ([version]$Version -le [version]$Current) { Fail "The new version must be higher than $Current." }
$Tag = "v$Version"
if (& git tag --list $Tag) { Fail "$Tag already exists." }

$Notes = "src\packaging\release-notes\versions\$Tag.md"
if (-not (Test-Path $Notes) -or -not (Get-Content $Notes -Raw).Trim()) {
    New-Item -ItemType Directory -Force (Split-Path $Notes) | Out-Null
    Set-Content -Path $Notes -Encoding utf8 -Value @"
- **Something new.** What it does for the user, in one or two sentences.
- **Something fixed.** What used to go wrong, and that it's fixed.
"@
    Start-Process notepad $Notes
    Fail @"
Write the patch notes for $Tag in the file that just opened ($Notes).
HyperFlux shows them in the update popup, so write them for users. Then commit and run this again.
Also update, when the change is important:
  - the Features list in README.md
  - the 'New in this update' notes on the home page (releaseNotes in src\web\HyperFlux Web.html)
"@
}

$Python = "src\python_embed\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
Write-Host "`nRunning the tests..."
& $Python -m unittest discover -s src\tests -t src
if ($LASTEXITCODE -ne 0) { Fail "Tests failed, so nothing was published." }

$text = [IO.File]::ReadAllText((Resolve-Path $VersionFile)) -replace '__version__ = "[^"]+"', "__version__ = `"$Version`""
[IO.File]::WriteAllText((Resolve-Path $VersionFile), $text, (New-Object Text.UTF8Encoding $false))
& git add $VersionFile $Notes
& git commit -m "Release $Tag"
if ($LASTEXITCODE -ne 0) { Fail "Could not commit the version change." }
& git tag -a $Tag -m "HyperFlux $Tag"
& git push origin $Branch
if ($LASTEXITCODE -ne 0) { Fail "Pushing $Branch failed. Fix it, then run: git push origin $Branch $Tag" }
& git push origin $Tag
if ($LASTEXITCODE -ne 0) { Fail "Pushing the tag failed. Run: git push origin $Tag" }

Write-Host "`n$Tag is on its way." -ForegroundColor Green
Write-Host "GitHub is building and testing the installer (about 10 minutes):"
Write-Host "  https://github.com/$Repo/actions"
Write-Host "When it's done, open the draft release, check it, and click Publish:"
Write-Host "  https://github.com/$Repo/releases"
Write-Host "Installed copies of HyperFlux will then offer the update within a few hours."
