@echo off
title GestorLab - Status do Congelamento (UWF)
color 0B

echo ================================================================
echo   GESTORLAB - Status do Congelamento de Disco (UWF)
echo ================================================================
echo.

where uwfmgr >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] O gerenciador UWF nao esta habilitado neste sistema operacional.
    echo Para habilitar, execute 'ativar_congelamento_uwf.bat' como Administrador.
    echo.
    pause
    exit /b
)

uwfmgr get-config
echo.
pause
