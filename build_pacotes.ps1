# Gera os pacotes de entrega a partir de server\, client\ e launcher\ (única fonte do código):
#   1_PROFESSOR\GestorLab Professor.exe + app\
#   2_ALUNO\GestorLab Aluno.exe + app\
# A pasta "dados" de cada pacote (banco, senhas, configuração) é preservada.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$basePy = Join-Path $root "python_app"          # Python embutido (modelo)
$sysPy = (& python -c "import sys; print(sys.base_prefix)").Trim()   # Python instalado (fonte do tkinter)

if (-not (Test-Path $csc)) { throw "csc.exe (.NET Framework) nao encontrado." }
if (-not (Test-Path "$basePy\python.exe")) { throw "python_app\python.exe nao encontrado." }

function New-Package($name, $exeName, $define, $icon, $requirements, $codeFiles, $withTk) {
    $pkg = Join-Path $root $name
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force $pkg | Out-Null

    # Remove só o que é gerado; "dados" fica.
    Get-ChildItem $pkg -Force | Where-Object { $_.Name -ne "dados" } | Remove-Item -Recurse -Force

    $py = Join-Path $pkg "app\python"
    $code = Join-Path $pkg "app\code"
    New-Item -ItemType Directory -Force $py, $code | Out-Null

    Write-Host "Python embutido..."
    Get-ChildItem $basePy -Force | Where-Object { $_.Name -ne "Lib" } | Copy-Item -Destination $py -Recurse -Force
    New-Item -ItemType Directory -Force "$py\Lib\site-packages" | Out-Null
    # python312._pth: define onde o Python procura módulos (inclui a pasta do código).
    Set-Content "$py\python312._pth" -Encoding ASCII -Value @("python312.zip", ".", "..\code", "Lib\site-packages", "import site")

    Write-Host "Dependencias ($requirements)..."
    & python -m pip install --quiet --disable-pip-version-check --target "$py\Lib\site-packages" -r (Join-Path $root $requirements)
    if ($LASTEXITCODE -ne 0) { throw "pip falhou" }

    if ($withTk) {
        Write-Host "tkinter..."
        Copy-Item "$sysPy\DLLs\_tkinter.pyd", "$sysPy\DLLs\tcl86t.dll", "$sysPy\DLLs\tk86t.dll", "$sysPy\DLLs\zlib1.dll" $py
        Copy-Item "$sysPy\Lib\tkinter" "$py\Lib\site-packages\tkinter" -Recurse
        Copy-Item "$sysPy\tcl" "$py\tcl" -Recurse
        Get-ChildItem "$py\tcl" -Recurse -Directory -Filter "demos" | Remove-Item -Recurse -Force
    }

    Write-Host "Codigo..."
    foreach ($f in $codeFiles) { Copy-Item (Join-Path $root $f) $code -Recurse -Force }
    Get-ChildItem $pkg -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

    Write-Host "Lancador..."
    $src = Join-Path $root "launcher\Launcher.cs"
    & $csc /nologo /target:winexe /platform:x64 /optimize+ "/define:$define" "/win32icon:$(Join-Path $root $icon)" `
        /r:System.Windows.Forms.dll "/out:$pkg\$exeName" $src
    if ($LASTEXITCODE -ne 0) { throw "csc falhou" }

    return $pkg
}

# ---------- Professor ----------
$prof = New-Package "1_PROFESSOR" "GestorLab Professor.exe" "PROFESSOR" "server\icon.ico" "requirements-professor.txt" `
    @("server\main.py", "server\auth.py", "server\config.py", "server\database.py", "server\static") $false
Copy-Item (Join-Path $root "liberar_firewall.bat") $prof

# ---------- Aluno ----------
$alu = New-Package "2_ALUNO" "GestorLab Aluno.exe" "ALUNO" "client\icon.ico" "requirements-aluno.txt" `
    @("client\agent.py", "client\logo.png") $true
New-Item -ItemType Directory -Force "$alu\dados" | Out-Null
if (-not (Test-Path "$alu\dados\config.json")) { Copy-Item (Join-Path $root "client\config.json") "$alu\dados\config.json" }
Copy-Item (Join-Path $root "congelamento") "$alu\congelamento" -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $root "instalar_aluno_todos_os_pcs.bat") $alu -Force

Write-Host "`nPronto!" -ForegroundColor Green
Write-Host "  $prof\GestorLab Professor.exe"
Write-Host "  $alu\GestorLab Aluno.exe  (config em 2_ALUNO\dados\config.json)"
