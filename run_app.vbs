Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

' A PowerShell 7 parent can leave incompatible modules ahead of Windows PowerShell's.
Set processEnv = WshShell.Environment("PROCESS")
processEnv("PSModulePath") = WshShell.ExpandEnvironmentStrings("%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules") & ";" & processEnv("PSModulePath")

repoRoot = fso.GetParentFolderName(WScript.ScriptFullName)
shellPath = repoRoot & "\src-tauri\target\debug\meowcal-sub-2-shell.exe"
corePath = repoRoot & "\src-tauri\resources\core\meowcal-core.exe"
coreLockPath = repoRoot & "\config\meowcal-core.lock.json"
webviewDataPath = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\com.meowcal.sub2\EBWebView"
eventLogOverride = WshShell.ExpandEnvironmentStrings("%MEOCOSUB2_EVENT_LOG_PATH%")
If eventLogOverride <> "" And eventLogOverride <> "%MEOCOSUB2_EVENT_LOG_PATH%" Then
  eventLogPath = eventLogOverride
  logDir = fso.GetParentFolderName(eventLogPath)
Else
  logDir = WshShell.ExpandEnvironmentStrings("%APPDATA%") & "\meowcal-sub-2\logs"
  eventLogPath = logDir & "\meowcal-sub-2.events.jsonl"
End If
uiDir = repoRoot & "\src\meocosub2\overlay\ui"
uiBuiltMarker = repoRoot & "\src\meocosub2\overlay\static\index.html"

Dim forceRebuild
forceRebuild = False
If WScript.Arguments.Count > 0 Then
  If LCase(WScript.Arguments(0)) = "--rebuild" Then
    forceRebuild = True
  End If
End If

Function Pad2(value)
  Pad2 = Right("0" & CStr(value), 2)
End Function

Function Pad4(value)
  Pad4 = Right("0000" & CStr(value), 4)
End Function

Function Hex4(value)
  Hex4 = Right("0000" & Hex(value), 4)
End Function

Function JsonEscape(value)
  Dim text, result, i, ch, code
  text = CStr(value)
  result = ""
  For i = 1 To Len(text)
    ch = Mid(text, i, 1)
    code = AscW(ch)
    If code < 0 Then code = code + 65536
    Select Case code
      Case 34
        result = result & "\" & Chr(34)
      Case 92
        result = result & "\\"
      Case 8
        result = result & "\b"
      Case 9
        result = result & "\t"
      Case 10
        result = result & "\n"
      Case 12
        result = result & "\f"
      Case 13
        result = result & "\r"
      Case Else
        If (code >= 0 And code <= 31) Or (code >= 127 And code <= 65535) Then
          result = result & "\u" & Hex4(code)
        Else
          result = result & ch
        End If
    End Select
  Next
  JsonEscape = result
End Function

Sub GetUtcClock(ByRef isoTimestamp, ByRef epochMs)
  Dim utc, utcDate
  isoTimestamp = ""
  epochMs = ""
  For Each utc In GetObject("winmgmts:\\.\root\cimv2").ExecQuery("SELECT Year,Month,Day,Hour,Minute,Second FROM Win32_UTCTime")
    utcDate = DateSerial(utc.Year, utc.Month, utc.Day) + TimeSerial(utc.Hour, utc.Minute, utc.Second)
    isoTimestamp = Pad4(utc.Year) & "-" & Pad2(utc.Month) & "-" & Pad2(utc.Day) & "T" & Pad2(utc.Hour) & ":" & Pad2(utc.Minute) & ":" & Pad2(utc.Second) & "Z"
    epochMs = CStr(DateDiff("s", DateSerial(1970, 1, 1), utcDate)) & "000"
    Exit Sub
  Next
  If isoTimestamp = "" Then
    utcDate = Now
    isoTimestamp = Pad4(Year(utcDate)) & "-" & Pad2(Month(utcDate)) & "-" & Pad2(Day(utcDate)) & "T" & Pad2(Hour(utcDate)) & ":" & Pad2(Minute(utcDate)) & ":" & Pad2(Second(utcDate)) & "Z"
    epochMs = CStr(DateDiff("s", DateSerial(1970, 1, 1), utcDate)) & "000"
  End If
End Sub

Sub EnsureFolder(folderPath)
  If folderPath = "" Or fso.FolderExists(folderPath) Then Exit Sub
  parentPath = fso.GetParentFolderName(folderPath)
  If parentPath <> "" And Not fso.FolderExists(parentPath) Then EnsureFolder parentPath
  If Not fso.FolderExists(folderPath) Then fso.CreateFolder folderPath
End Sub

Sub EnsureLogDir()
  EnsureFolder logDir
End Sub

Sub LogEvent(eventName, fieldsJson)
  Dim isoTimestamp, epochMs
  On Error Resume Next
  EnsureLogDir
  GetUtcClock isoTimestamp, epochMs
  Set logFile = fso.OpenTextFile(eventLogPath, 8, True)
  logFile.WriteLine "{""ts"":""" & JsonEscape(isoTimestamp) & """,""ts_ms"":" & epochMs & ",""layer"":""launcher"",""level"":""info"",""event"":""" & JsonEscape(eventName) & """," & fieldsJson & "}"
  logFile.Close
  On Error GoTo 0
End Sub

Sub RunCleanup()
  Dim command
  LogEvent "launcher.cleanup.start", """repoRoot"":""" & JsonEscape(repoRoot) & """"
  command = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command " & Chr(34) & _
    "$ErrorActionPreference='SilentlyContinue'; " & _
    "for($i = 0; $i -lt 2; $i++) { " & _
    "Get-Process -Name 'meowcal-sub-2-shell' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; " & _
    "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and ($_.CommandLine -like '*meocosub2.cli serve*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; " & _
    "Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; " & _
    "Start-Sleep -Milliseconds 300 " & _
    "}" & Chr(34)
  WshShell.Run command, 0, True
  LogEvent "launcher.cleanup.done", """port"":8765"
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
    corePath, _
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
LogEvent "launcher.start", """repoRoot"":""" & JsonEscape(repoRoot) & """,""forceRebuild"":" & LCase(CStr(forceRebuild))
RunCleanup

LogEvent "launcher.core.prepare.start", """lockPath"": """ & JsonEscape(coreLockPath) & """"
coreResult = WshShell.Run( _
  "powershell -NoProfile -ExecutionPolicy Bypass -File """ & repoRoot & "\scripts\fetch-meowcal-core.ps1"" -UsePrepared", _
  0, _
  True _
)
If coreResult <> 0 Then
  LogEvent "launcher.core.prepare.failed", """exitCode"":" & CStr(coreResult)
  MsgBox "Meowcal Core could not be prepared. Check the release lock and network connection.", vbCritical, "Meowcal Sub 2"
  WScript.Quit coreResult
End If
LogEvent "launcher.core.prepare.done", """path"": """ & JsonEscape(corePath) & """"

' Only wipe WebView cache on explicit --rebuild (forces full WebView reinit otherwise)
If forceRebuild And fso.FolderExists(webviewDataPath) Then
  On Error Resume Next
  fso.DeleteFolder webviewDataPath, True
  On Error GoTo 0
  LogEvent "launcher.webview_cache.deleted", """path"":""" & JsonEscape(webviewDataPath) & """"
End If

If forceRebuild Or IsUIRebuildNeeded() Then
  WshShell.CurrentDirectory = uiDir
  LogEvent "launcher.ui_build.start", """cwd"":""" & JsonEscape(uiDir) & """"
  WshShell.Run "cmd /c npm run build", 1, True
  LogEvent "launcher.ui_build.done", """cwd"":""" & JsonEscape(uiDir) & """"
End If

If forceRebuild Or IsRebuildNeeded() Then
  WshShell.CurrentDirectory = repoRoot & "\src-tauri"
  LogEvent "launcher.shell_build.start", """cwd"":""" & JsonEscape(WshShell.CurrentDirectory) & """"
  buildResult = WshShell.Run("cmd /c cargo build 2>&1 && echo BUILD_OK || echo BUILD_FAILED", 1, True)
  LogEvent "launcher.shell_build.done", """exitCode"":" & CStr(buildResult)
End If

If fso.FileExists(shellPath) Then
  LogEvent "launcher.shell.launch", """path"":""" & JsonEscape(shellPath) & """"
  WshShell.Environment("PROCESS")("MEOWCAL_CORE_PROFILE") = "development"
  WshShell.Run Chr(34) & shellPath & Chr(34), 0, False
Else
  LogEvent "launcher.shell.missing", """path"":""" & JsonEscape(shellPath) & """"
  MsgBox "Binary not found — run with --rebuild to force a build.", vbCritical, "Meowcal Sub 2"
End If
