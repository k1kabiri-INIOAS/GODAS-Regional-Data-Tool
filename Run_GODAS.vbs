Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
shell.Run "pythonw.exe """ & base & "\main.pyw""", 0, False
Set fso = Nothing
Set shell = Nothing
