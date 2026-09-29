' ===================================================================
'  Literature Survey Agent - desktop launcher (windowless wrapper)
'
'  Starts 启动器.ps1 without a console window. The GUI itself is the
'  window the user sees; a black PowerShell console behind it would
'  look broken.
'
'  ASCII-only on purpose: Windows Script Host decodes .vbs files as the
'  system ANSI codepage, so non-ASCII here would break parsing.
' ===================================================================
Option Explicit

Dim fso, shell, root, script, cmd
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
script = fso.BuildPath(root, ChrW(21551) & ChrW(21160) & ChrW(22120) & ".ps1")

' Fallback: find the launcher by pattern if the name above does not match
If Not fso.FileExists(script) Then
    Dim f, found
    found = ""
    For Each f In fso.GetFolder(root).Files
        If LCase(fso.GetExtensionName(f.Name)) = "ps1" Then
            If InStr(f.Name, "launcher") > 0 Or InStr(f.Name, "start") > 0 Then
                found = f.Path
            End If
        End If
    Next
    If found <> "" Then script = found
End If

If Not fso.FileExists(script) Then
    MsgBox "Launcher script not found in:" & vbCrLf & root, 16, "Literature Survey Agent"
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """"

' 0 = hidden console window; False = do not wait (the GUI keeps running)
shell.Run cmd, 0, False
