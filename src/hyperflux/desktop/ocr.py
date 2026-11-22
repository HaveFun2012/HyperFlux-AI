"""Reads the text in a picture with the OCR engine Windows already has.

Nothing to install and nothing leaves the PC: a short Windows PowerShell script asks
Windows.Media.Ocr for the words and where they are, and the rows are put back together
here. OCR only reads text; it cannot describe a photo (that is the image helper's job).
"""

import base64
import binascii
import json
import os
import subprocess
import tempfile
from pathlib import Path

MAX_IMAGE_BYTES = 20 * 1024 * 1024
SMALL_TEXT_PIXELS = 12  # median word height below this (a 14 px font measures about 10) is "small"
ENLARGE = 3
TIMEOUT_SECONDS = 60

# Prints one JSON object: {"language": "...", "words": [{"t": text, "x": left, "y": top, "h": height}]}.
_SCRIPT = r"""
param([string]$Path, [string]$Scales = '1')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing
foreach ($type in 'Windows.Media.Ocr.OcrEngine, Windows.Foundation', 'Windows.Globalization.Language, Windows.Globalization',
    'Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics', 'Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics',
    'Windows.Storage.StorageFile, Windows.Storage', 'Windows.Storage.FileAccessMode, Windows.Storage',
    'Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams') {
    $parts = $type.Split(',')
    $null = Invoke-Expression ('[' + $parts[0] + ', ' + $parts[1].Trim() + ', ContentType = WindowsRuntime]')
}
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($operation, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $null = $task.Wait(-1)
    $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('en-US')) }
if (-not $engine) { Write-Output '{"error": "no OCR language is installed in Windows"}'; exit 0 }

$passes = New-Object System.Collections.ArrayList
foreach ($scaleText in $Scales.Split(',')) {
    $Scale = [double]$scaleText
    $source = $Path
    if ($Scale -ne 1) {
        $image = [System.Drawing.Image]::FromFile($Path)
        $bitmap = New-Object System.Drawing.Bitmap ([int]($image.Width * $Scale)), ([int]($image.Height * $Scale))
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.DrawImage($image, 0, 0, $bitmap.Width, $bitmap.Height)
        $source = $Path + '.scaled.png'
        $bitmap.Save($source, [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.Dispose(); $bitmap.Dispose(); $image.Dispose()
    }
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($source)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $software = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($software)) ([Windows.Media.Ocr.OcrResult])
    $stream.Dispose()
    $words = New-Object System.Collections.ArrayList
    foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            $box = $word.BoundingRect
            $clean = $word.Text -replace '[\p{Cc}"\\]', ''
            $null = $words.Add(@{ t = $clean; x = $box.X / $Scale; y = $box.Y / $Scale; h = $box.Height / $Scale })
        }
    }
    $null = $passes.Add(@{ scale = $Scale; words = @($words) })
}
if ($Path + '.scaled.png' | Test-Path) { Remove-Item ($Path + '.scaled.png') -ErrorAction SilentlyContinue }
@{ language = $engine.RecognizerLanguage.LanguageTag; passes = @($passes) } | ConvertTo-Json -Depth 5 -Compress
"""


def group_rows(words):
    """Put words that sit on the same row together, left to right, top to bottom.

    Windows OCR reads a table or a receipt column by column; people read it by row.
    """
    rows = []
    for word in sorted(words, key=lambda w: w["y"] + w["h"] / 2):
        middle = word["y"] + word["h"] / 2
        for row in rows:
            if abs(row["middle"] - middle) < 0.5 * max(row["height"], word["h"]):
                row["words"].append(word)
                break
        else:
            rows.append({"middle": middle, "height": word["h"], "words": [word]})
    return "\n".join(
        " ".join(w["t"] for w in sorted(row["words"], key=lambda w: w["x"]))
        for row in sorted(rows, key=lambda r: r["middle"])
    )


def _run(path, scales):
    script = Path(tempfile.gettempdir()) / "hyperflux-ocr.ps1"
    script.write_text(_SCRIPT, encoding="utf-8-sig")  # PowerShell 5.1 wants a BOM for UTF-8
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    completed = subprocess.run(
        [str(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Path", str(path), "-Scales", ",".join(str(s) for s in scales)],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = completed.stdout.strip()
    if not output:
        raise OSError((completed.stderr or "The OCR engine returned nothing.").strip()[:300])
    # Windows PowerShell 5.1 writes some control characters (a stray BEL from a misread
    # glyph) into the JSON as they are; they are never real text.
    data = json.loads("".join(c for c in output if c >= " "))
    if data.get("error"):
        raise OSError(data["error"])
    return data.get("passes") or []


def choose_pass(passes):
    """The reading to keep. Normal-size text is read best as it is. Small text is where
    Windows OCR slips (a 9 px line came back as 6 words of 19), so for that the enlarged
    copy wins unless it found far fewer words than the original."""
    if not passes:
        return []
    original = passes[0]["words"]
    heights = sorted(w["h"] for w in original)
    small = not original or heights[len(heights) // 2] < SMALL_TEXT_PIXELS
    if not small:
        return original
    best = original
    for candidate in passes[1:]:
        if len(candidate["words"]) >= 0.7 * len(best) and len(candidate["words"]) > 0:
            best = candidate["words"]
    return best


def read_text(path):
    """The text in the picture at `path`, one line per row ('' when there is none)."""
    return group_rows(choose_pass(_run(path, (1, ENLARGE))))



def read_data_url(data_url):
    """OCR a picture sent as a data: URL (what the page keeps for an attached image)."""
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Send the picture as a data URL.")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=False)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The picture could not be decoded.") from error
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("The picture is empty or larger than 20 MB.")
    handle, name = tempfile.mkstemp(suffix=".png", prefix="hyperflux-ocr-")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(raw)
        return read_text(name)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
