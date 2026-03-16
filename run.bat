@echo off
setlocal

set COMPOSE_FILE=docker-compose.yml
set DEV_COMPOSE_FILE=docker-compose.dev.yml
set E2E_COMPOSE_FILE=docker-compose.e2e.yml
set FS_E2E_COMPOSE_FILE=docker-compose.fs-e2e.yml
set PROJECT_NAME=librariarr
set SERVICE=librariarr
set DEV_SERVICE=librariarr-dev
set DEV_UI_SERVICE=librariarr-ui-dev
set DEV_RADARR_SERVICE=radarr-dev
set DEV_SONARR_SERVICE=sonarr-dev
set E2E_SERVICE=librariarr-radarr-e2e
set FS_E2E_SERVICE=librariarr-e2e

if "%~1"=="" goto :usage

if /I "%~1"=="setup" goto :setup
if /I "%~1"=="install" goto :install
if /I "%~1"=="build" goto :build
if /I "%~1"=="up" goto :up
if /I "%~1"=="down" goto :down
if /I "%~1"=="restart" goto :restart
if /I "%~1"=="logs" goto :logs
if /I "%~1"=="once" goto :once
if /I "%~1"=="test" goto :test
if /I "%~1"=="e2e" goto :e2e
if /I "%~1"=="fs-e2e" goto :fse2e
if /I "%~1"=="quality" goto :quality
if /I "%~1"=="quality-autofix" goto :qualityautofix
if /I "%~1"=="dev-up" goto :devup
if /I "%~1"=="dev-reset" goto :devreset
if /I "%~1"=="dev-bootstrap" goto :devbootstrap
if /I "%~1"=="dev-seed" goto :devseed
if /I "%~1"=="dev-down" goto :devdown
if /I "%~1"=="dev-logs" goto :devlogs
if /I "%~1"=="dev-shell" goto :devshell

goto :usage

:setup
if exist config.yaml\NUL (
  dir /b config.yaml | findstr . >nul
  if errorlevel 1 (
    rmdir config.yaml
    copy /Y config.yaml.example config.yaml >nul
    echo Replaced empty config.yaml directory with config file from config.yaml.example
  ) else (
    echo Error: config.yaml is a directory with contents. Move/remove it, then run run.bat setup.
    exit /b 1
  )
) else (
  if not exist config.yaml (
    copy /Y config.yaml.example config.yaml >nul
    echo Created config.yaml from config.yaml.example
  ) else (
    echo config.yaml already exists
  )
)
goto :eof

:install
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% build %DEV_SERVICE%
goto :eof

:build
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% build %SERVICE%
goto :eof

:up
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% up -d %SERVICE%
goto :eof

:down
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% down
goto :eof

:restart
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% restart %SERVICE%
goto :eof

:logs
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% logs -f %SERVICE%
goto :eof

:once
docker compose -p %PROJECT_NAME% -f %COMPOSE_FILE% run --rm %SERVICE% --config /config/config.yaml --once
goto :eof

:test
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m 'not e2e and not fs_e2e' -p no:cacheprovider"
goto :eof

:e2e
if not exist .e2e-data\arr-e2e\movies mkdir .e2e-data\arr-e2e\movies
if not exist .e2e-data\arr-e2e\radarr_library mkdir .e2e-data\arr-e2e\radarr_library
if not exist .e2e-data\arr-e2e\series mkdir .e2e-data\arr-e2e\series
if not exist .e2e-data\arr-e2e\sonarr_library mkdir .e2e-data\arr-e2e\sonarr_library
docker compose -p %PROJECT_NAME% -f %E2E_COMPOSE_FILE% down -v --remove-orphans >nul 2>&1
docker compose -p %PROJECT_NAME% -f %E2E_COMPOSE_FILE% run --rm %E2E_SERVICE%
goto :eof

:fse2e
if not exist .e2e-data mkdir .e2e-data
docker compose -p %PROJECT_NAME% -f %FS_E2E_COMPOSE_FILE% run --rm %FS_E2E_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m fs_e2e -p no:cacheprovider"
goto :eof

:quality
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app bash ./tools/run_backend_quality.sh check"
if errorlevel 1 exit /b %errorlevel%
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_UI_SERVICE% "sh /app/tools/run_frontend_quality.sh check"
if errorlevel 1 exit /b %errorlevel%
goto :eof

:qualityautofix
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app bash ./tools/run_backend_quality.sh autofix"
if errorlevel 1 exit /b %errorlevel%
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_UI_SERVICE% "sh /app/tools/run_frontend_quality.sh autofix"
if errorlevel 1 exit /b %errorlevel%
goto :eof

:devup
call "%~f0" setup
if errorlevel 1 exit /b 1
if not exist .env if exist .env.dev.example (
  copy /Y .env.dev.example .env >nul
  echo Created .env from .env.dev.example
)
if not exist data\dev-config mkdir data\dev-config
call tools\dev_prepare_media_layout.bat
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% up -d %DEV_SERVICE% %DEV_UI_SERVICE% %DEV_RADARR_SERVICE% %DEV_SONARR_SERVICE%
if not "%LIBRARIARR_DEV_BOOTSTRAP%"=="0" call "%~f0" dev-bootstrap

set "WEB_PORT=%LIBRARIARR_WEB_PORT%"
if "%WEB_PORT%"=="" set "WEB_PORT=8787"
set "RADARR_PORT=%DEV_HOST_PORT_RADARR%"
if "%RADARR_PORT%"=="" set "RADARR_PORT=17878"
set "SONARR_PORT=%DEV_HOST_PORT_SONARR%"
if "%SONARR_PORT%"=="" set "SONARR_PORT=18989"
echo.
echo Dev services are up. Open:
echo - LibrariArr admin GUI: http://localhost:%WEB_PORT%
echo - Vite dev UI:           http://localhost:5173
echo - Radarr admin:          http://localhost:%RADARR_PORT%
echo - Sonarr admin:          http://localhost:%SONARR_PORT%
goto :eof

:devreset
call "%~f0" dev-down
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm --user 0:0 %DEV_SERVICE% "chown -R ${PUID:-1000}:${PGID:-1000} /data /config || true"

if exist data\dev-media\movies rd /s /q data\dev-media\movies
if exist data\dev-media\series rd /s /q data\dev-media\series
if exist data\dev-media\radarr_library rd /s /q data\dev-media\radarr_library
if exist data\dev-media\sonarr_library rd /s /q data\dev-media\sonarr_library
if exist data\dev-config rd /s /q data\dev-config

mkdir data\dev-media\movies
mkdir data\dev-media\series
mkdir data\dev-media\radarr_library
mkdir data\dev-media\sonarr_library
mkdir data\dev-config

call "%~f0" dev-up
if errorlevel 1 exit /b 1
call "%~f0" dev-seed
goto :eof

:devbootstrap
call "%~f0" setup
if errorlevel 1 exit /b 1
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm --user 0:0 %DEV_SERVICE% "chown -R ${PUID:-1000}:${PGID:-1000} /config && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.media_permissions"
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.bootstrap"
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% restart %DEV_SERVICE%
goto :eof

:devseed
call "%~f0" setup
if errorlevel 1 exit /b 1
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm --user 0:0 %DEV_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.seed && python -m librariarr.dev.media_permissions"
goto :eof

:devdown
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% down
goto :eof

:devlogs
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% logs -f %DEV_SERVICE% %DEV_UI_SERVICE% %DEV_RADARR_SERVICE% %DEV_SONARR_SERVICE%
goto :eof

:devshell
docker compose -p %PROJECT_NAME% -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% bash
goto :eof

:usage
echo Usage: run.bat ^<command^>
echo.
echo Commands:
echo   setup       Create config.yaml from example if missing
echo   install     Build dev image with dependencies (cached)
echo   build       Build the production image
echo   up          Start service in background
echo   down        Stop and remove service containers
echo   restart     Restart service
echo   logs        Tail service logs
echo   once        Run one reconcile cycle and exit
echo   test        Run unit tests in Docker
echo   e2e         Run end-to-end integration tests against live Arr services
echo   fs-e2e      Run end-to-end filesystem tests in Docker
echo   quality     Run lint/format/complexity/LOC checks in Docker
echo   quality-autofix  Apply auto-fixes, then run quality checks
echo   dev-up      Start dev API, UI, Sonarr, and Radarr services
echo   dev-reset   Stop dev stack, wipe dev data/config, start stack, and reseed
echo   dev-bootstrap  Configure dev Arr instances and sync API keys into config.yaml
echo   dev-seed    Create fake movie/series folders/files in configured source roots
echo   dev-down    Stop dev services
echo   dev-logs    Tail dev service logs
echo   dev-shell   Open shell in dev container
exit /b 1
