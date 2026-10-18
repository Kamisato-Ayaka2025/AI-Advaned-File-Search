# Build a single-file qqmd.exe with PyInstaller (run on Windows).
# Requires: python -m pip install pyinstaller sqlcipher3-binary zstandard cryptography
# ffmpeg.exe must be placed next to qqmd.exe (WXGF transcoding) or on PATH.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$scripts = @(
  'wechat4_extract_keys.py','wechat4_decrypt.py','wechat4_export_md.py',
  'wechat4_decode_images.py','wechat4_find_image_key.py',
  'wechat_media_index.py','ntqq_export_md.py','validate_format.py'
)

$add = @()
foreach ($s in $scripts) { $add += @('--add-data', "$s;.") }

python -m PyInstaller --onefile --name qqmd --clean --noconfirm `
  @add --collect-all sqlcipher3 qqmd.py

Write-Host "`nBuilt: dist\qqmd.exe"
Write-Host "把 ffmpeg.exe 放到 dist\ 同目录，然后运行： dist\qqmd.exe doctor"
