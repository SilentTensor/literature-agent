' ===================================================================
'  Literature Survey Agent - windowless PowerShell runner
'
'  Runs a PowerShell script with NO console window at all.
'
'  Why this exists: a Scheduled Task that runs powershell.exe directly
'  shows a black console window every time it fires. The watchdogs run
'  once a minute, so the user sees a terminal flashing constantly.
'  WScript.Shell.Run with window style 0 starts it fully hidden.
'
'  Usage:   wscript.exe run-hidden.vbs <script-name.ps1>
'  Example: wscript.exe run-hidden.vbs watchdog.ps1
'
'  ASCII-only on purpose: Windows Script Host decodes .vbs files as the
'  system ANSI codepage, so non-ASCII here would break parsing.
'  Note: VBScript has no "|" operator and no "Empty;" statement.
' ===================================================================
Option Explicit

Dim fso, shell, root, target, script, cmd, logFile, ts

Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)

' Which script to run: first argument, default watchdog.ps1
If WScript.Arguments.Count >= 1 Then
    target = WScript.Arguments(0)
Else
    target = "watchdog.ps1"
End If

script = fso.BuildPath(root, target)

' Never show a MsgBox here: an error dialog would itself be an
' interruption, and on a Scheduled Task it would hang forever.
If Not fso.FileExists(script) Then
    logFile = fso.BuildPath(root, "logs\launcher.log")
    If Not fso.FolderExists(fso.BuildPath(root, "logs")) Then
        fso.CreateFolder(fso.BuildPath(root, "logs"))
    End If
    Set ts = fso.OpenTextFile(logFile, 8, True)
    ts.WriteLine Now & "  ERROR: script not found: " & script
    ts.Close
    WScript.Quit 1
End If

cmd = "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden " & _
      "-ExecutionPolicy Bypass -File """ & script & """"

' 0 = hidden window, False = do not wait for it to finish
shell.Run cmd, 0, False

WScript.Quit 0
