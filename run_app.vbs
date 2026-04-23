Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

repoRoot = fso.GetParentFolderName(WScript.ScriptFullName)
webviewDataPath = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\com.meowcal.sub2\EBWebView"

Sub RunCleanup()
  Dim command
  command = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command " & Chr(34) & _
    "$ErrorActionPreference='SilentlyContinue'; " & _
    "for($i = 0; $i -lt 8; $i++) { " & _
    "Get-Process -Name 'meowcal-sub-2-shell' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; " & _
    "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and (($_.CommandLine -like '*meocosub2.cli serve*') -or ($_.CommandLine -like '*meocosub2.cli gui*')) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; " & _
    "Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; " & _
    "Start-Sleep -Milliseconds 300 " & _
    "}" & Chr(34)
  WshShell.Run command, 0, True
End Sub

WshShell.CurrentDirectory = repoRoot
RunCleanup
If fso.FolderExists(webviewDataPath) Then
  On Error Resume Next
  fso.DeleteFolder webviewDataPath, True
  On Error GoTo 0
End If
WScript.Sleep 1200

WshShell.CurrentDirectory = repoRoot & "\src-tauri"
WshShell.Run "cmd /k cargo tauri dev", 1, False
