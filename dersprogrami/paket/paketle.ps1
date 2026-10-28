# Ders Programi - kapali ag kurulum paketi olusturur (internetli bir Windows 10/11 64 bit bilgisayarda).
# Sonuc: dist\DersProgrami-YYYYMMDD.zip  ->  icinde tasinabilir Python, tum paketler ve program.
# Bilgisayarda Python kurulu olmasi gerekmez; Python'un "embeddable" surumu indirilip pakete konur.
param(
    [string]$PythonVersion = "3.12.10"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest ilerleme cubugu indirmeyi cok yavaslatir

$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$build = Join-Path $dist "DersProgrami"
$cache = Join-Path $dist "indirilenler"
Write-Host "[1/6] Klasor hazirlaniyor: $build"
if (Test-Path $build) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $build, $cache | Out-Null

Write-Host "[2/6] Program dosyalari kopyalaniyor..."
$excludeDirs = @(".git", ".venv", "venv", "dist", "yedekler", "staticfiles", "__pycache__", "paket")
$excludeFiles = @("db.sqlite3", ".env", "*.pyc", "calistir.bat", "calistir.sh", "kurulum.bat", "kurulum.sh",
                  "Dockerfile", "docker-compose.yml", "docker-entrypoint.sh", "Caddyfile", ".dockerignore", "*.log")
robocopy $root $build /E /XD $excludeDirs /XF $excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Dosyalar kopyalanamadi (robocopy $LASTEXITCODE)" }
foreach ($f in "kurulum.bat", "baslat.bat", "guncelle.bat", "otomatik_baslat.bat", "OKUBENI.txt") {
    Copy-Item (Join-Path $PSScriptRoot $f) $build
}

Write-Host "[3/6] Python $PythonVersion (embeddable, 64 bit) indiriliyor..."
$embed = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $embed)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $embed
}
$py = Join-Path $build "python"
Expand-Archive $embed -DestinationPath $py
# ._pth: site-packages ve proje klasoru (..) yola eklenir, "import site" acilir.
$pth = Get-ChildItem $py -Filter "python*._pth" | Select-Object -First 1
$stdlib = (Get-ChildItem $py -Filter "python3*.zip" | Select-Object -First 1).Name
Set-Content -Path $pth.FullName -Encoding ASCII -Value @($stdlib, ".", "Lib\site-packages", "..", "import site")
$python = Join-Path $py "python.exe"

Write-Host "[4/6] pip kuruluyor..."
$getpip = Join-Path $cache "get-pip.py"
if (-not (Test-Path $getpip)) { Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip }
& $python $getpip --no-warn-script-location --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip kurulamadi" }

Write-Host "[5/6] Paketler indirilip kuruluyor (OR-Tools, Django, ...)..."
& $python -m pip install --no-warn-script-location --disable-pip-version-check -r (Join-Path $build "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Paketler kurulamadi" }
# Pakette calistigini dogrula
Push-Location $build
try {
    & $python -c "import django, ortools, waitress, reportlab, openpyxl, tzdata; print('Paketler tamam')"
    if ($LASTEXITCODE -ne 0) { throw "Paket denetimi basarisiz" }
    & $python manage.py check
    if ($LASTEXITCODE -ne 0) { throw "manage.py check basarisiz" }
} finally { Pop-Location }
Get-ChildItem $build -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item (Join-Path $build "db.sqlite3") -ErrorAction SilentlyContinue  # denetim bos veritabani olusturabilir

Write-Host "[6/6] Zip olusturuluyor..."
$zip = Join-Path $dist ("DersProgrami-" + (Get-Date -Format "yyyyMMdd") + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
tar.exe -a -c -f $zip -C $dist DersProgrami
if ($LASTEXITCODE -ne 0) { throw "Zip olusturulamadi" }
$size = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host ""
Write-Host "Hazir: $zip ($size MB)"
Write-Host "Bu dosyayi kapali agdaki sunucu bilgisayara tasiyin, acin ve kurulum.bat'a cift tiklayin."
