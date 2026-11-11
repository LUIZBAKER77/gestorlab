' GestorLab Aluno - inicia o agente pelo Python oficial (pythonw.exe), sem janela.
' Roda o pythonw.exe (assinado) em vez de um .exe proprio, o que evita que o
' antivirus trate o programa como desconhecido. Comportamento identico ao do .exe.
Option Explicit
Dim oShell, oFSO, sBase, sPython, sScript
Set oShell = CreateObject("WScript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")

sBase = oFSO.GetParentFolderName(WScript.ScriptFullName)
sPython = sBase & "\app\python\pythonw.exe"
sScript = sBase & "\app\code\agent.py"

If Not oFSO.FileExists(sPython) Or Not oFSO.FileExists(sScript) Then
    MsgBox "Arquivos do programa nao encontrados na pasta 'app'." & vbCrLf & _
           "Copie a pasta inteira, nao so este arquivo.", vbExclamation, "GestorLab"
    WScript.Quit 1
End If

' Pasta de dados (banco/config/logs) e o caminho deste .vbs para o inicio automatico.
oShell.Environment("Process")("GESTORLAB_DATA") = sBase & "\dados"
oShell.Environment("Process")("GESTORLAB_VBS") = WScript.ScriptFullName
oShell.CurrentDirectory = sBase & "\app\code"

' 0 = janela oculta; False = nao espera terminar.
oShell.Run """" & sPython & """ """ & sScript & """", 0, False
