; Sub 2 keeps its configuration, logs and subtitle downloads, and Meowcal Core
; keeps the translation engine, outside this app's identifier folders, so
; "Delete the application data" does not reach them on its own.
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    RmDir /r "$APPDATA\meowcal-sub-2"
    RmDir /r "$PROFILE\.cache\meowcal-sub-2"
    ; Core keeps every Meowcal app's production engine here. Meowcal Sub may
    ; still run from it, so keep it once that app has run.
    ${IfNot} ${FileExists} "$APPDATA\com.meowcal.sub\*.*"
    ${AndIfNot} ${FileExists} "$LOCALAPPDATA\com.meowcal.sub\*.*"
      RmDir /r "$LOCALAPPDATA\Meowcal\Core\production"
    ${EndIf}
    RmDir "$LOCALAPPDATA\Meowcal\Core"
    RmDir "$LOCALAPPDATA\Meowcal"
  ${EndIf}
!macroend
