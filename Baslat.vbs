Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
python = folder & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(python) Then
  shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\start.py" & Chr(34), 0, False
Else
  shell.Run Chr(34) & folder & "\Baslat.cmd" & Chr(34), 1, False
End If
