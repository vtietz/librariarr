@echo off
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
pushd "%REPO_ROOT%" >nul

set "MEDIA_ROOT_VALUE=%MEDIA_ROOT%"

if not defined MEDIA_ROOT_VALUE if exist .env (
  for /f "usebackq tokens=1* delims==" %%A in (`findstr /R /B /C:"MEDIA_ROOT=" ".env"`) do (
    if /I "%%A"=="MEDIA_ROOT" set "MEDIA_ROOT_VALUE=%%B"
  )
)

if not defined MEDIA_ROOT_VALUE set "MEDIA_ROOT_VALUE=.\data\dev-media"
set "MEDIA_ROOT_VALUE=!MEDIA_ROOT_VALUE:/=\!"

if "!MEDIA_ROOT_VALUE:~0,2!"==".\" (
  set "MEDIA_ROOT_PATH=%CD%\!MEDIA_ROOT_VALUE:~2!"
) else if "!MEDIA_ROOT_VALUE:~1,1!"==":" (
  set "MEDIA_ROOT_PATH=!MEDIA_ROOT_VALUE!"
) else if "!MEDIA_ROOT_VALUE:~0,1!"=="\" (
  set "MEDIA_ROOT_PATH=!MEDIA_ROOT_VALUE!"
) else (
  set "MEDIA_ROOT_PATH=%CD%\!MEDIA_ROOT_VALUE!"
)

set "CREATE_FAIL=0"
if not exist "!MEDIA_ROOT_PATH!\movies" mkdir "!MEDIA_ROOT_PATH!\movies" 2>nul || set "CREATE_FAIL=1"
if not exist "!MEDIA_ROOT_PATH!\series" mkdir "!MEDIA_ROOT_PATH!\series" 2>nul || set "CREATE_FAIL=1"
if not exist "!MEDIA_ROOT_PATH!\radarr_library" mkdir "!MEDIA_ROOT_PATH!\radarr_library" 2>nul || set "CREATE_FAIL=1"
if not exist "!MEDIA_ROOT_PATH!\sonarr_library" mkdir "!MEDIA_ROOT_PATH!\sonarr_library" 2>nul || set "CREATE_FAIL=1"

if "!CREATE_FAIL!"=="1" (
  echo Info: host pre-create skipped for !MEDIA_ROOT_PATH!; in-container repair runs during dev-bootstrap
) else (
  echo Ensured dev media directories under !MEDIA_ROOT_PATH!
)

popd >nul
exit /b 0
