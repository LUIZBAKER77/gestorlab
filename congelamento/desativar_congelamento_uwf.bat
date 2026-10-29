@echo off
title GestorLab - Desativar Congelamento do Sistema (UWF)
color 0C

echo ================================================================
echo   GESTORLAB - Desativacao Temporaria do Congelamento (Modo Manutencao)
echo ================================================================
echo.
echo Use este script quando precisar:
echo - Instalar novos softwares no computador
echo - Atualizar o Windows ou drivers
echo - Fazer configuracoes permanentes
echo.

:: Verifica Administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Voce precisa executar este arquivo como ADMINISTRADOR!
    echo Clique com o botao direito nele e escolha "Executar como administrador".
    echo.
    pause
    exit /b
)

echo Desativando filtro de protecao de escrita...
uwfmgr filter disable

echo.
echo ================================================================
echo   FILTRO DESATIVADO!
echo   Reinicie o computador para entrar no Modo de Manutencao.
echo   Todas as alteracoes feitas apos reiniciar ficarao salvas.
echo   Quando terminar, execute 'ativar_congelamento_uwf.bat' novamente.
echo ================================================================
echo.
set /p REBOOT="Deseja reiniciar este computador agora para manutencao? (S/N): "
if /i "%REBOOT%"=="S" (
    shutdown /r /t 5 /c "Reiniciando para entrar em modo manutencao..."
)

pause
