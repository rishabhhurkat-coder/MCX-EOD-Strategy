Option Explicit

Dim fso, shell, projectRoot, pythonw, python, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = "C:\Program Files\Python312\pythonw.exe"
python = "C:\Program Files\Python312\python.exe"

If fso.FileExists(pythonw) Then
    command = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & projectRoot & "\backend\launch_ui.py" & Chr(34)
Else
    command = Chr(34) & python & Chr(34) & " " & Chr(34) & projectRoot & "\backend\launch_ui.py" & Chr(34)
End If

shell.Run command, 0, False
