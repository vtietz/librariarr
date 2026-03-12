@echo off
setlocal

set COMPOSE_FILE=docker-compose.yml
set DEV_COMPOSE_FILE=docker-compose.dev.yml
set E2E_COMPOSE_FILE=docker-compose.e2e.yml
set FS_E2E_COMPOSE_FILE=docker-compose.fs-e2e.yml
set SERVICE=librariarr
set DEV_SERVICE=librariarr-dev
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
if /I "%~1"=="radarr-e2e" goto :radarre2e
if /I "%~1"=="sonarr-e2e" goto :sonarre2e
if /I "%~1"=="quality" goto :quality
if /I "%~1"=="quality-autofix" goto :qualityautofix
if /I "%~1"=="dev-up" goto :devup
if /I "%~1"=="dev-down" goto :devdown
if /I "%~1"=="dev-logs" goto :devlogs
if /I "%~1"=="dev-shell" goto :devshell

goto :usage

:setup
if not exist config.yaml (
  copy /Y config.yaml.example config.yaml >nul
  echo Created config.yaml from config.yaml.example
) else (
  echo config.yaml already exists
)
goto :eof

:install
docker compose -f %DEV_COMPOSE_FILE% build %DEV_SERVICE%
goto :eof

:build
docker compose -f %COMPOSE_FILE% build %SERVICE%
goto :eof

:up
docker compose -f %COMPOSE_FILE% up -d %SERVICE%
goto :eof

:down
docker compose -f %COMPOSE_FILE% down
goto :eof

:restart
docker compose -f %COMPOSE_FILE% restart %SERVICE%
goto :eof

:logs
docker compose -f %COMPOSE_FILE% logs -f %SERVICE%
goto :eof

:once
docker compose -f %COMPOSE_FILE% run --rm %SERVICE% --config /config/config.yaml --once
goto :eof

:test
docker compose -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m 'not e2e and not fs_e2e and not radarr_e2e and not sonarr_e2e' -p no:cacheprovider"
goto :eof

:e2e
if not exist .e2e-data\radarr-e2e\movies mkdir .e2e-data\radarr-e2e\movies
if not exist .e2e-data\radarr-e2e\radarr_library mkdir .e2e-data\radarr-e2e\radarr_library
docker compose -f %E2E_COMPOSE_FILE% down -v --remove-orphans >nul 2>&1
docker compose -f %E2E_COMPOSE_FILE% run --rm %E2E_SERVICE%
goto :eof

:fse2e
if not exist .e2e-data mkdir .e2e-data
docker compose -f %FS_E2E_COMPOSE_FILE% run --rm %FS_E2E_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m fs_e2e -p no:cacheprovider"
goto :eof

:radarre2e
if not exist .e2e-data\radarr-e2e\movies mkdir .e2e-data\radarr-e2e\movies
if not exist .e2e-data\radarr-e2e\radarr_library mkdir .e2e-data\radarr-e2e\radarr_library
docker compose -f %E2E_COMPOSE_FILE% down -v --remove-orphans >nul 2>&1
docker compose -f %E2E_COMPOSE_FILE% run --rm %E2E_SERVICE%
goto :eof

:sonarre2e
if not exist .e2e-data\radarr-e2e\movies mkdir .e2e-data\radarr-e2e\movies
if not exist .e2e-data\radarr-e2e\radarr_library mkdir .e2e-data\radarr-e2e\radarr_library
docker compose -f %E2E_COMPOSE_FILE% down -v --remove-orphans >nul 2>&1
docker compose -f %E2E_COMPOSE_FILE% run --rm %E2E_SERVICE%
goto :eof

:quality
docker compose -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --no-cache && PYTHONPATH=/app ruff format --check . --no-cache && radon cc -s -n B librariarr tests && radon raw -s librariarr tests"
goto :eof

:qualityautofix
docker compose -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --fix --no-cache && PYTHONPATH=/app ruff format . --no-cache && radon cc -s -n B librariarr tests && radon raw -s librariarr tests"
goto :eof

:devup
docker compose -f %DEV_COMPOSE_FILE% up -d %DEV_SERVICE%
goto :eof

:devdown
docker compose -f %DEV_COMPOSE_FILE% down
goto :eof

:devlogs
docker compose -f %DEV_COMPOSE_FILE% logs -f %DEV_SERVICE%
goto :eof

:devshell
docker compose -f %DEV_COMPOSE_FILE% run --rm %DEV_SERVICE% bash
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
echo   radarr-e2e  Alias for e2e
echo   sonarr-e2e  Alias for e2e
echo   quality     Run lint/format/complexity/LOC checks in Docker
echo   quality-autofix  Apply auto-fixes, then run quality checks
echo   dev-up      Start dev profile service in background
echo   dev-down    Stop dev profile service
echo   dev-logs    Tail dev profile logs
echo   dev-shell   Open shell in dev container
exit /b 1
