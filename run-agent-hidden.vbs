' ===================================================================
'  Literature Survey Agent - windowless launcher
'  Starts run-agent.ps1 with a hidden window, so no console flashes up.
'  Called from the Startup folder or a Scheduled Task.
'
'  NOTE: ASCII-only on purpose. Windows Script Host decodes .vbs files
'  as the system ANSI codepage (GBK on zh-CN), so non-ASCII characters
'  here would break parsing with "unterminated string constant".
'
'  Usage:  wscript.exe run-agent-hidden.vbs
' ===================================================================
Option Explicit

Dim fso, shell, root, script, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root   = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(root, "run-agent.ps1")

If Not fso.FileExists(script) Then
    MsgBox "Launcher not found: " & script, 16, "Literature Survey Agent"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & script & """"

' 0 = hidden window, False = do not wait
shell.Run cmd, 0, False
