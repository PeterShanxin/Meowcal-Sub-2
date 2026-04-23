Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

repoRoot = fso.GetParentFolderName(WScript.ScriptFullName)
shellPath = repoRoot & "\src-tauri\target\debug\meowcal-sub-2-shell.exe"
webviewDataPath = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\com.meowcal.sub2\EBWebView"
uiDir = repoRoot & "\src\meocosub2\overlay\ui"
uiBuiltMarker = repoRoot & "\src\meocosub2\overlay\static\index.html"

Dim forceRebuild
forceRebuild = False
If WScript.Arguments.Count > 0 Then
  If LCase(WScript.Arguments(0)) = "--rebuild" Then
    forceRebuild = True
  End If
End If

Sub RunCleanup()
  Dim command
  command = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command " & Chr(34) & _
    "$ErrorActionPreference='SilentlyContinue'; " & _
    "for($i = 0; $i -lt 2; $i++) { " & _
    "Get-Process -Name 'meowcal-sub-2-shell' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; " & _
    "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and (($_.CommandLine -like '*meocosub2.cli serve*') -or ($_.CommandLine -like '*meocosub2.cli gui*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; " & _
    "Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; " & _
    "Start-Sleep -Milliseconds 300 " & _
    "}" & Chr(34)
  WshShell.Run command, 0, True
End Sub

Function CheckFolderNewer(folderPath, exeTime)
  CheckFolderNewer = False
  If Not fso.FolderExists(folderPath) Then Exit Function
  Dim folder, file, subFolder
  Set folder = fso.GetFolder(folderPath)
  For Each file In folder.Files
    If LCase(Right(file.Name, 3)) = ".rs" Then
      If file.DateLastModified > exeTime Then
        CheckFolderNewer = True
        Exit Function
      End If
    End If
  Next
  For Each subFolder In folder.SubFolders
    If CheckFolderNewer(subFolder.Path, exeTime) Then
      CheckFolderNewer = True
      Exit Function
    End If
  Next
End Function

Function IsRebuildNeeded()
  If Not fso.FileExists(shellPath) Then
    IsRebuildNeeded = True
    Exit Function
  End If
  Dim exeTime
  exeTime = fso.GetFile(shellPath).DateLastModified
  Dim f
  For Each f In Array( _
    repoRoot & "\src-tauri\Cargo.toml", _
    repoRoot & "\src-tauri\tauri.conf.json", _
    repoRoot & "\src-tauri\build.rs", _
    repoRoot & "\Cargo.lock" _
  )
    If fso.FileExists(f) Then
      If fso.GetFile(f).DateLastModified > exeTime Then
        IsRebuildNeeded = True
        Exit Function
      End If
    End If
  Next
  If CheckFolderNewer(repoRoot & "\src-tauri\src", exeTime) Then
    IsRebuildNeeded = True
    Exit Function
  End If
  IsRebuildNeeded = False
End Function

Function CheckUIFolderNewer(folderPath, refTime)
  CheckUIFolderNewer = False
  If Not fso.FolderExists(folderPath) Then Exit Function
  Dim folder, file, subFolder, ext
  Set folder = fso.GetFolder(folderPath)
  For Each file In folder.Files
    ext = LCase(fso.GetExtensionName(file.Name))
    If ext = "ts" Or ext = "tsx" Or ext = "js" Or ext = "jsx" Or ext = "css" Or ext = "html" Then
      If file.DateLastModified > refTime Then
        CheckUIFolderNewer = True
        Exit Function
      End If
    End If
  Next
  For Each subFolder In folder.SubFolders
    If LCase(subFolder.Name) <> "node_modules" And LCase(subFolder.Name) <> "dist" Then
      If CheckUIFolderNewer(subFolder.Path, refTime) Then
        CheckUIFolderNewer = True
        Exit Function
      End If
    End If
  Next
End Function

Function IsUIRebuildNeeded()
  If Not fso.FileExists(uiBuiltMarker) Then
    IsUIRebuildNeeded = True
    Exit Function
  End If
  Dim refTime
  refTime = fso.GetFile(uiBuiltMarker).DateLastModified
  Dim f
  For Each f In Array( _
    uiDir & "\index.html", _
    uiDir & "\vite.config.ts", _
    uiDir & "\package.json", _
    uiDir & "\tsconfig.json" _
  )
    If fso.FileExists(f) Then
      If fso.GetFile(f).DateLastModified > refTime Then
        IsUIRebuildNeeded = True
        Exit Function
      End If
    End If
  Next
  If CheckUIFolderNewer(uiDir & "\src", refTime) Then
    IsUIRebuildNeeded = True
    Exit Function
  End If
  IsUIRebuildNeeded = False
End Function

WshShell.CurrentDirectory = repoRoot
RunCleanup

' Only wipe WebView cache on explicit --rebuild (forces full WebView reinit otherwise)
If forceRebuild And fso.FolderExists(webviewDataPath) Then
  On Error Resume Next
  fso.DeleteFolder webviewDataPath, True
  On Error GoTo 0
End If

If forceRebuild Or IsUIRebuildNeeded() Then
  WshShell.CurrentDirectory = uiDir
  WshShell.Run "cmd /c npm run build", 1, True
End If

If forceRebuild Or IsRebuildNeeded() Then
  WshShell.CurrentDirectory = repoRoot & "\src-tauri"
  buildResult = WshShell.Run("cmd /c cargo build 2>&1 && echo BUILD_OK || echo BUILD_FAILED", 1, True)
End If

If fso.FileExists(shellPath) Then
  WshShell.Run Chr(34) & shellPath & Chr(34), 0, False
Else
  MsgBox "Binary not found — run with --rebuild to force a build.", vbCritical, "Meowcal Sub 2"
End If
