@echo off
title GestorLab - Ativar Congelamento do Sistema (UWF)
color 0A

echo ================================================================
echo   GESTORLAB - Ativacao do Congelamento de Disco (UWF Nativo)
echo   Ambiente: Windows 10 / 11 Pro, Education ou Enterprise
echo ================================================================
echo.
echo Este script ativara o recurso oficial da Microsoft:
echo Unified Write Filter (UWF).
echo.
echo Ao ativar, QUALQUER arquivo criado, baixado ou alterado pelo
echo aluno na unidade C: sera automaticamente DESCARTADO ao reiniciar!
echo.

:: Verifica se esta rodando como Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Voce precisa executar este arquivo como ADMINISTRADOR!
    echo Clique com o botao direito nele e escolha "Executar como administrador".
    echo.
    pause
    exit /b
)

echo [1/4] Habilitando recurso Unified Write Filter no Windows...
dism /online /enable-feature /featureName:Client-UnifiedWriteFilter /all /norestart
if %errorlevel% neq 0 (
    echo [AVISO] Falha ao habilitar recurso via DISM. Verifique se a edicao e Windows Pro/Enterprise.
)

echo.
echo [2/4] Configurando o gerenciador UWF...
uwfmgr filter enable
uwfmgr overlay set-size 2048
uwfmgr overlay set-type RAM

echo.
echo [3/4] Protegendo a unidade C:...
uwfmgr volume protect C:

echo.
echo [4/4] Verificando status da configuracao...
uwfmgr get-config

echo.
echo ================================================================
echo   CONGELAMENTO CONFIGURADO COM SUCESSO!
echo   Para que o congelamento passe a valer, o computador precisa
echo   ser REINICIADO.
echo ================================================================
echo.
set /p REBOOT="Deseja reiniciar este computador agora? (S/N): "
if /i "%REBOOT%"=="S" (
    shutdown /r /t 5 /c "Reiniciando para ativar o congelamento de disco..."
) else (
    echo Lembre-se de reiniciar manualmente antes de liberar aos alunos.
)

pause
