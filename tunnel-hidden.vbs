' ===================================================================
'  Literature Survey Agent - public tunnel launcher (windowless)
'
'  Starts localtunnel for the local service and writes the public URL
'  to public-url.txt. ASCII-only on purpose: Windows Script Host
'  decodes .vbs as the system ANSI codepage, so non-ASCII here would
'  break parsing with "unterminated string constant".
'
'  Usage:  wscript.exe tunnel-hidden.vbs
' ===================================================================
Option Explicit

Dim fso, shell, root, ps1, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1  = fso.BuildPath(root, "tunnel.ps1")

If Not fso.FileExists(ps1) Then
    MsgBox "Launcher not found: " & ps1, 16, "Literature Survey Agent"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"

' 0 = hidden window, False = do not wait
shell.Run cmd, 0, False
