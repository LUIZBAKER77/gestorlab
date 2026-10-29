@echo off
title GestorLab - Liberar Firewall do Windows
color 0A

echo =======================================================
echo   GESTORLAB - Liberar Firewall do Windows
echo =======================================================
echo.
echo Este script libera as portas 8000 (Painel e Transmissao) 
echo e 8001 (Descoberta Automatica na Rede Local) no Firewall.
echo.
echo OBS: Execute este arquivo como ADMINISTRADOR no PC do Professor!
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ATENCAO] Voce precisa executar este arquivo como Administrador!
    echo Clique com o botao direito nele e escolha "Executar como administrador".
    echo.
    pause
    exit /b
)

echo Liberando porta 8000 TCP (Servidor Web / WebSockets)...
netsh advfirewall firewall delete rule name="GestorLab_Server_TCP8000" >nul 2>&1
netsh advfirewall firewall add rule name="GestorLab_Server_TCP8000" dir=in action=allow protocol=TCP localport=8000 profile=any >nul 2>&1

echo Liberando porta 8001 UDP (Descoberta Automatica na Rede Escolar)...
netsh advfirewall firewall delete rule name="GestorLab_Discovery_UDP8001" >nul 2>&1
netsh advfirewall firewall add rule name="GestorLab_Discovery_UDP8001" dir=in action=allow protocol=UDP localport=8001 profile=any >nul 2>&1

echo.
echo =======================================================
echo [SUCESSO] Portas liberadas com sucesso no Firewall!
echo Os computadores dos alunos agora poderao se conectar.
echo =======================================================
echo.
pause

