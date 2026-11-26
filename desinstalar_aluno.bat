@echo off
rem ============================================================================
rem  Remove o GestorLab Aluno do PC: fecha o agente, tira o inicio automatico,
rem  reativa o Gerenciador de Tarefas e apaga as pastas C:\2_ALUNO e C:\GestorLab.
rem  NAO precisa de internet. Clique com o botao direito > "Executar como
rem  administrador" (funciona tambem no Modo de Seguranca).
rem ============================================================================
setlocal
set "EXE=GestorLab Aluno.exe"

echo Fechando o agente (se estiver em execucao)...
taskkill /F /IM "%EXE%" >nul 2>&1

echo Removendo o inicio automatico...
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v GestorLabAgent /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v GestorLabAgent /f >nul 2>&1
schtasks /Delete /F /TN "GestorLab Aluno" >nul 2>&1

echo Reativando o Gerenciador de Tarefas...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\System" /v DisableTaskMgr /f >nul 2>&1

echo Apagando a pasta do programa...
for %%D in ("C:\2_ALUNO" "C:\GestorLab") do if exist "%%~D" rmdir /S /Q "%%~D"

echo.
echo GestorLab removido. Reinicie o PC para concluir.
echo (Se este arquivo estava dentro de C:\GestorLab, ele sera apagado no fim - normal.)
pause
exit /b 0
