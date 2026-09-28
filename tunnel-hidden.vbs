' ===================================================================
'  Literature Survey Agent - public tunnel launcher (windowless)
'  Starts tunnel_manager.py (Cloudflare quick tunnel).
'  ASCII-only: Windows Script Host decodes .vbs as ANSI.
' ===================================================================
Option Explicit

Dim fso, shell, root, ps1, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
ps1  = fso.BuildPath(root, "tunnel-watchdog.ps1")

If Not fso.FileExists(ps1) Then
    MsgBox "Launcher not found: " & ps1, 16, "Literature Survey Agent"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & ps1 & """"
shell.Run cmd, 0, False
