@echo off
rem ============================================================================
rem  Instala o GestorLab Aluno no DISCO do PC (C:\GestorLab) para todos os usuarios.
rem
rem  Como usar:
rem   - Manual: clique com o botao direito neste arquivo > "Executar como administrador".
rem   - Em massa: GPO > Configuracao do Computador > Scripts > Inicializacao,
rem     apontando para este arquivo na pasta de rede (roda como SISTEMA, sem perguntas).
rem
rem  Depois de instalado, o programa inicia sozinho com o Windows, sem a caixa
rem  "Abrir arquivo - Aviso de seguranca" (ela so aparece para programas em disco de rede).
rem  Pode rodar de novo para ATUALIZAR: fecha o agente, troca os arquivos e atualiza o
rem  config.json (servidor/TLS/chave), preservando o resto da pasta "dados" (logs, regras).
rem ============================================================================
setlocal
set "ORIGEM=%~dp0"
set "DESTINO=C:\GestorLab"
set "EXE=GestorLab Aluno.exe"

if not exist "%ORIGEM%%EXE%" (
    echo Nao encontrei "%EXE%" ao lado deste script. Rode-o de dentro da pasta 2_ALUNO.
    exit /b 1
)

rem Se o programa estiver aberto, fecha-o para liberar os arquivos (ao encerrar o .exe,
rem o pythonw filho tambem e encerrado pelo job). Assim a reinstalacao nao trava.
tasklist /fi "imagename eq %EXE%" 2>nul | find /i "%EXE%" >nul
if not errorlevel 1 (
    echo Fechando o GestorLab para atualizar...
    taskkill /F /IM "%EXE%" >nul 2>&1
    rem Da um tempo para os arquivos liberarem antes de copiar.
    ping -n 3 127.0.0.1 >nul
)

if not exist "%DESTINO%" mkdir "%DESTINO%"
rem Todos os usuarios do PC precisam gravar logs e configuracoes (S-1-5-32-545 = Usuarios).
icacls "%DESTINO%" /grant *S-1-5-32-545:(OI)(CI)M /C /Q >nul 2>&1

robocopy "%ORIGEM%." "%DESTINO%" /E /XD dados /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo Falha ao copiar os arquivos para %DESTINO%.
    exit /b 1
)
if not exist "%DESTINO%\dados" (
    if exist "%ORIGEM%dados" robocopy "%ORIGEM%dados" "%DESTINO%\dados" /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
)

rem Atualiza SEMPRE o config.json (servidor, TLS/pin, agent_key), mesmo numa
rem reinstalacao, preservando o resto da pasta dados (logs, regras salvas).
if not exist "%DESTINO%\dados" mkdir "%DESTINO%\dados"
if exist "%ORIGEM%dados\config.json" copy /Y "%ORIGEM%dados\config.json" "%DESTINO%\dados\config.json" >nul

rem Inicio automatico para todos os usuarios (chave do computador, nao do usuario).
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v GestorLabAgent /t REG_SZ /d "\"%DESTINO%\%EXE%\" --autostart" /f >nul
if errorlevel 1 (
    echo Nao consegui registrar o inicio automatico. Execute como Administrador.
    exit /b 1
)

echo GestorLab instalado em %DESTINO% e configurado para iniciar com o Windows.
echo Ele passa a funcionar no proximo login (ou de duplo clique em "%DESTINO%\%EXE%").
exit /b 0
