; PartAudit - Windows installer (NSIS 3, Unicode). Built by tools/build_installer.py, which passes:
;   /DVERSION=2.1.0  /DSRC=<staged program folder>  /DOUTFILE=<setup .exe>
; A per-user installation (no administrator rights): the program goes to %LOCALAPPDATA%\Programs\PartAudit.
; The first start installs a private Python environment (internet, a few minutes) - see PartAudit-Windows.bat.
; The installer is not signed: Windows SmartScreen asks "More info" > "Run anyway".
Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user
!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
Name "PartAudit ${VERSION}"
Caption "PartAudit ${VERSION} – התקנה"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\PartAudit"
InstallDirRegKey HKCU "Software\PartAudit" "InstallDir"
BrandingText "PartAudit ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1037 "ProductName" "PartAudit"
VIAddVersionKey /LANG=1037 "FileDescription" "PartAudit – בקרת נתונים הנדסיים"
VIAddVersionKey /LANG=1037 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1037 "LegalCopyright" "PartAudit"

!define MUI_ICON "${SRC}\installer\partaudit.ico"
!define MUI_UNICON "${SRC}\installer\partaudit.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "PartAudit – בקרת נתונים הנדסיים"
!define MUI_WELCOMEPAGE_TEXT "התוכנה מוצאת חלקים שרשומים יותר מפעם אחת ב-PDM, ב-PLM וב-ERP, ומראה מה לתקן.$\r$\n$\r$\nהיא רק קוראת מהמערכות שלכם – היא לא כותבת אליהן ולא שולחת נתונים החוצה.$\r$\n$\r$\nההתקנה היא למשתמש הזה בלבד ולא צריכה הרשאות מנהל. בהפעלה הראשונה התוכנה מורידה את רכיבי Python שלה (כ-150 MB)."
!define MUI_FINISHPAGE_RUN "$INSTDIR\PartAudit-Windows.bat"
!define MUI_FINISHPAGE_RUN_TEXT "להפעיל את PartAudit עכשיו"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\START-HERE.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "לפתוח את ההוראות הקצרות"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${SRC}\installer\notice-he.txt"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Hebrew"

!define UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\PartAudit"

Section "PartAudit (חובה)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; an update replaces the program; the workspace (%USERPROFILE%\PartAudit) and its data are never touched
  RMDir /r "$INSTDIR\part_audit"
  File /r "${SRC}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\PartAudit" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST}" "DisplayName" "PartAudit"
  WriteRegStr HKCU "${UNINST}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST}" "Publisher" "PartAudit"
  WriteRegStr HKCU "${UNINST}" "DisplayIcon" "$INSTDIR\installer\partaudit.ico"
  WriteRegStr HKCU "${UNINST}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINST}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "${UNINST}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST}" "NoRepair" 1
  CreateDirectory "$SMPROGRAMS\PartAudit"
  CreateShortcut "$SMPROGRAMS\PartAudit\PartAudit.lnk" "$INSTDIR\PartAudit-Windows.bat" "" "$INSTDIR\installer\partaudit.ico" 0
  CreateShortcut "$SMPROGRAMS\PartAudit\הוראות.lnk" "$INSTDIR\START-HERE.txt"
  CreateShortcut "$SMPROGRAMS\PartAudit\הסרת PartAudit.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section "קיצור דרך בשולחן העבודה" SecDesktop
  CreateShortcut "$DESKTOP\PartAudit.lnk" "$INSTDIR\PartAudit-Windows.bat" "" "$INSTDIR\installer\partaudit.ico" 0
SectionEnd

Section /o "שרת צוות וסריקה מתוזמנת" SecServer
  ; the computer that serves the whole team: everyone opens it in the browser and signs in
  CreateShortcut "$SMPROGRAMS\PartAudit\PartAudit – שרת צוות.lnk" "$INSTDIR\PartAudit-Server.bat" "" "$INSTDIR\installer\partaudit.ico" 0
  CreateShortcut "$SMPROGRAMS\PartAudit\PartAudit – סריקה עכשיו.lnk" "$INSTDIR\PartAudit-Rescan.bat" "" "$INSTDIR\installer\partaudit.ico" 0
SectionEnd

LangString DESC_Main ${LANG_HEBREW} "התוכנה עצמה, עם סביבת ההדגמה (מפעל בדוי)."
LangString DESC_Desktop ${LANG_HEBREW} "סמל של PartAudit בשולחן העבודה."
LangString DESC_Server ${LANG_HEBREW} "רק למחשב שישמש שרת לכל הצוות: קיצור דרך להפעלת השרת ולסריקה (למשל ממתזמן המשימות של Windows)."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_Main)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_Desktop)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecServer} $(DESC_Server)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Delete "$DESKTOP\PartAudit.lnk"
  RMDir /r "$SMPROGRAMS\PartAudit"
  RMDir /r "$INSTDIR"
  ; the private Python environment the first start installed
  RMDir /r "$LOCALAPPDATA\PartAudit\venv"
  RMDir "$LOCALAPPDATA\PartAudit"
  DeleteRegKey HKCU "${UNINST}"
  DeleteRegKey HKCU "Software\PartAudit"
  MessageBox MB_OK|MB_ICONINFORMATION "PartAudit הוסר.$\r$\n$\r$\nתיקיית העבודה $PROFILE\PartAudit נשארה במקומה – שם התוצאות, ההחלטות וקובצי ה-Excel. אפשר למחוק אותה ידנית."
SectionEnd
