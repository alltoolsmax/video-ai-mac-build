# Tai ffmpeg va Real-ESRGAN vao thu muc bin cua ban build.
# Dung:  powershell -ExecutionPolicy Bypass -File build\fetch_tools.ps1 -Dest "dist\VideoAI-MrHuynh\bin"
param([string]$Dest = "bin")
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$tmp = Join-Path $env:TEMP ("videoai_tools_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Get-Zip($url, $name) {
    $zip = Join-Path $tmp "$name.zip"
    Write-Host "  - Tai $name ..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $out = Join-Path $tmp $name
    Expand-Archive -Path $zip -DestinationPath $out -Force
    return $out
}

# ffmpeg + ffprobe
try {
    if (-not (Test-Path (Join-Path $Dest "ffmpeg\ffmpeg.exe"))) {
        $d = Get-Zip "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "ffmpeg"
        $fdir = Join-Path $Dest "ffmpeg"
        New-Item -ItemType Directory -Force -Path $fdir | Out-Null
        Get-ChildItem $d -Recurse -Include ffmpeg.exe, ffprobe.exe | ForEach-Object { Copy-Item $_.FullName $fdir -Force }
        Write-Host "    OK: ffmpeg"
    } else { Write-Host "  - ffmpeg da co" }
} catch { Write-Warning "Khong tai duoc ffmpeg: $_  (Cong Cu Video se can ffmpeg trong PATH)" }

# Real-ESRGAN ncnn-vulkan
try {
    if (-not (Test-Path (Join-Path $Dest "realesrgan\realesrgan-ncnn-vulkan.exe"))) {
        $d = Get-Zip "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip" "realesrgan"
        $rdir = Join-Path $Dest "realesrgan"
        New-Item -ItemType Directory -Force -Path $rdir | Out-Null
        $exe = Get-ChildItem $d -Recurse -Filter realesrgan-ncnn-vulkan.exe | Select-Object -First 1
        Copy-Item (Join-Path $exe.DirectoryName "*") $rdir -Recurse -Force
        Write-Host "    OK: Real-ESRGAN"
    } else { Write-Host "  - Real-ESRGAN da co" }
} catch { Write-Warning "Khong tai duoc Real-ESRGAN: $_  (Nang Cap Anh se dung che do Lanczos)" }

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
