"""Takes still frames out of a video with the media decoder Windows already has.

A vision model looks at pictures, not at video, so a video is given to it as a few frames
taken evenly through it, each with its time. Nothing to install and nothing leaves the PC:
a short Windows PowerShell script asks Windows.Media.Editing for the frames. It reads what
Windows can play (H.264 MP4, which phones record, among others). The sound is not read.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".avi", ".wmv", ".mkv", ".webm")
MAX_VIDEO_BYTES = 300 * 1024 * 1024
FRAME_MAX_SIDE = 768  # enough to see a scene; more pixels only make each frame slower
MAX_FRAMES = 8
TIMEOUT_SECONDS = 180

# Prints one JSON object: {"duration": s, "width": w, "height": h, "frames": [{"time": s, "jpeg": base64}]}.
_SCRIPT = r"""
param([string]$Path, [string]$Counts, [int]$MaxSide)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
foreach ($type in 'Windows.Storage.StorageFile, Windows.Storage', 'Windows.Media.Editing.MediaClip, Windows.Media.Editing',
    'Windows.Media.Editing.MediaComposition, Windows.Media.Editing', 'Windows.Graphics.Imaging.ImageStream, Windows.Graphics.Imaging') {
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
try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $clip = Await ([Windows.Media.Editing.MediaClip]::CreateFromFileAsync($file)) ([Windows.Media.Editing.MediaClip])
    $composition = New-Object Windows.Media.Editing.MediaComposition
    # PowerShell 5.1 can't call Add on a Windows list directly.
    $null = [System.Collections.Generic.ICollection[Windows.Media.Editing.MediaClip]].GetMethod('Add').Invoke($composition.Clips, [object[]]@($clip))
    $duration = $composition.Duration.TotalSeconds
    $video = $clip.GetVideoEncodingProperties()
    $width = [int]$video.Width; $height = [int]$video.Height
    if ($duration -le 0 -or $width -le 0 -or $height -le 0) { throw 'no picture in this file' }
    # Counts is "short,normal,long": fewer frames for a clip of a few seconds, more for a long one.
    $choices = $Counts.Split(',') | ForEach-Object { [int]$_ }
    $count = if ($duration -le 3) { $choices[0] } elseif ($duration -le 60) { $choices[1] } else { $choices[2] }
    $scale = [Math]::Min(1.0, $MaxSide / [Math]::Max($width, $height))
    $frameWidth = [int]([Math]::Round($width * $scale / 2) * 2)
    $frameHeight = [int]([Math]::Round($height * $scale / 2) * 2)
    $frames = New-Object System.Collections.ArrayList
    for ($i = 0; $i -lt $count; $i++) {
        $second = $duration * ($i + 0.5) / $count  # the middle of each equal part
        $stream = Await ($composition.GetThumbnailAsync([TimeSpan]::FromSeconds($second), $frameWidth, $frameHeight,
            [Windows.Media.Editing.VideoFramePrecision]::NearestFrame)) ([Windows.Graphics.Imaging.ImageStream])
        $memory = New-Object System.IO.MemoryStream
        [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream).CopyTo($memory)
        $null = $frames.Add(@{ time = [Math]::Round($second, 1); jpeg = [Convert]::ToBase64String($memory.ToArray()) })
    }
    @{ duration = [Math]::Round($duration, 1); width = $width; height = $height; frames = @($frames) } | ConvertTo-Json -Depth 4 -Compress
} catch {
    @{ error = [string]$_.Exception.GetBaseException().Message } | ConvertTo-Json -Compress
}
"""


def is_video_name(name):
    return Path(str(name or "")).suffix.lower() in VIDEO_SUFFIXES


def parse_result(output):
    """The script's JSON -> {duration, frames: [{time, image: data URL}]}; OSError when it failed."""
    try:
        data = json.loads("".join(c for c in output if c >= " "))
    except json.JSONDecodeError as error:
        raise OSError("The video decoder returned something unreadable.") from error
    if data.get("error"):
        raise OSError("Windows could not read this video (" + str(data["error"]).strip()[:200] +
                      "). An H.264 MP4 works best.")
    frames = [{"time": frame["time"], "image": "data:image/jpeg;base64," + frame["jpeg"]}
              for frame in data.get("frames") or [] if frame.get("jpeg")]
    if not frames:
        raise OSError("No frames could be taken from this video.")
    return {"duration": data.get("duration"), "frames": frames}


def extract_frames(path, counts=(2, 4, 6), max_side=FRAME_MAX_SIDE):
    """Frames spread evenly through the video at `path`. counts: how many for a clip of up to
    3 seconds, up to a minute, and longer."""
    counts = [max(1, min(MAX_FRAMES, int(n))) for n in counts]
    script = Path(tempfile.gettempdir()) / "hyperflux-video.ps1"
    script.write_text(_SCRIPT, encoding="utf-8-sig")  # PowerShell 5.1 wants a BOM for UTF-8
    shell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    completed = subprocess.run(
        [str(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Path", str(Path(path).resolve()), "-Counts", ",".join(map(str, counts)), "-MaxSide", str(max_side)],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = completed.stdout.strip()
    if not output:
        raise OSError((completed.stderr or "The video decoder returned nothing.").strip()[:300])
    return parse_result(output)
