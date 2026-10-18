# Build a single-file qqmd.exe with PyInstaller (run on Windows).
# Requires: python -m pip install pyinstaller zstandard cryptography
# Optional: put ffmpeg.exe next to qqmd.exe for WXGF (image) transcoding.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$data = @(
  'wechat4_extract_keys.py','wechat4_decrypt.py','wechat4_decrypt_pure.py',
  'wechat4_export_md.py','wechat4_decode_images.py','wechat4_find_image_key.py',
  'wechat_media_index.py','ntqq_export_md.py','validate_format.py'
)
$add = @(); foreach ($f in $data) { $add += @('--add-data', "$f;.") }

python -m PyInstaller --onefile --name qqmd --clean --noconfirm `
  --hidden-import zstandard `
  --hidden-import cryptography.hazmat.primitives.ciphers `
  --hidden-import ctypes.wintypes `
  --collect-submodules zstandard `
  @add qqmd.py

Write-Host "`nBuilt: dist\qqmd.exe"
Write-Host "可选：把 ffmpeg.exe 放到 dist\ 同目录，再运行 dist\qqmd.exe doctor"
