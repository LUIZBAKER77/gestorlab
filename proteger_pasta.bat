@echo off
rem ============================================================================
rem  Protege a pasta do GestorLab Aluno contra o proprio aluno (rode UMA vez
rem  por PC, como ADMINISTRADOR, depois de extrair a pasta, ex.: C:\2_ALUNO).
rem
rem  - So administradores podem apagar, mover ou alterar a pasta.
rem  - A conta do laboratorio so le e executa; grava apenas onde o agente
rem    precisa: dados\ (logs, regras) e app\code\ (auto-atualizacao).
rem  - config.json (servidor, chave) fica somente leitura para a conta do lab.
rem  - Cria uma tarefa agendada (so administrador apaga) que abre o agente
rem    quando a conta do laboratorio entra no Windows.
rem ============================================================================
setlocal
net session >nul 2>&1
if errorlevel 1 (
    echo Precisa rodar como ADMINISTRADOR: botao direito ^> "Executar como administrador".
    pause
    exit /b 1
)

set "PASTA=%~dp0"
if "%PASTA:~-1%"=="\" set "PASTA=%PASTA:~0,-1%"
set "EXE=%PASTA%\GestorLab Aluno.exe"
if not exist "%EXE%" (
    echo Nao achei "%EXE%". Coloque este arquivo dentro da pasta do GestorLab Aluno.
    pause
    exit /b 1
)

set "CONTA="
set /p CONTA=Nome da conta do Windows do laboratorio (ex.: lab.info):
if "%CONTA%"=="" (
    echo Conta nao informada.
    pause
    exit /b 1
)

echo.
echo Aplicando permissoes em %PASTA% ...
rem Dono = Administradores (o dono sempre pode mudar as permissoes).
icacls "%PASTA%" /setowner *S-1-5-32-544 /T /C /Q >nul
rem Administradores e SYSTEM: controle total. Usuarios: ler e executar.
icacls "%PASTA%" /inheritance:r /grant:r *S-1-5-32-544:(OI)(CI)F *S-1-5-18:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX /T /C /Q
if errorlevel 1 goto erro
rem Pastas onde o agente grava.
icacls "%PASTA%\dados" /grant *S-1-5-32-545:(OI)(CI)M /T /C /Q
icacls "%PASTA%\app\code" /grant *S-1-5-32-545:(OI)(CI)M /T /C /Q
rem Configuracao: somente leitura.
if exist "%PASTA%\dados\config.json" icacls "%PASTA%\dados\config.json" /inheritance:r /grant:r *S-1-5-32-544:F *S-1-5-18:F *S-1-5-32-545:R /C /Q
rem Desinstalador nao fica no PC do aluno.
if exist "%PASTA%\desinstalar_aluno.bat" del /F /Q "%PASTA%\desinstalar_aluno.bat"

echo Criando inicio automatico protegido para a conta %CONTA% ...
schtasks /Create /F /TN "GestorLab Aluno" /TR "\"%EXE%\" --autostart" /SC ONLOGON /RU "%CONTA%" /IT /RL LIMITED >nul
if errorlevel 1 echo (Aviso: nao consegui criar a tarefa agendada. O inicio pelo registro continua valendo.)

echo.
echo Pronto. A conta do laboratorio nao consegue mais apagar nem alterar o programa.
echo Para remover depois: rode desinstalar_aluno.bat como administrador.
pause
exit /b 0

:erro
echo Falha ao aplicar as permissoes.
pause
exit /b 1
