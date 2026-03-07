@echo off
setlocal

set COMPOSE_FILE=docker-compose.yml
set SERVICE=librariarr
set DEV_SERVICE=librariarr-dev

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
docker compose -f %COMPOSE_FILE% --profile dev build %DEV_SERVICE%
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
docker compose -f %COMPOSE_FILE% --profile dev run --rm %DEV_SERVICE% "PYTHONPATH=/app pytest -q"
goto :eof

:quality
docker compose -f %COMPOSE_FILE% --profile dev run --rm %DEV_SERVICE% "PYTHONPATH=/app ruff check . && PYTHONPATH=/app ruff format --check . && radon cc -s -n B librariarr tests && radon raw -s librariarr tests"
goto :eof

:qualityautofix
docker compose -f %COMPOSE_FILE% --profile dev run --rm %DEV_SERVICE% "PYTHONPATH=/app ruff check . --fix && PYTHONPATH=/app ruff format . && radon cc -s -n B librariarr tests && radon raw -s librariarr tests"
goto :eof

:devup
docker compose -f %COMPOSE_FILE% --profile dev up -d %DEV_SERVICE%
goto :eof

:devdown
docker compose -f %COMPOSE_FILE% --profile dev down
goto :eof

:devlogs
docker compose -f %COMPOSE_FILE% --profile dev logs -f %DEV_SERVICE%
goto :eof

:devshell
docker compose -f %COMPOSE_FILE% --profile dev run --rm %DEV_SERVICE% bash
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
echo   quality     Run lint/format/complexity/LOC checks in Docker
echo   quality-autofix  Apply auto-fixes, then run quality checks
echo   dev-up      Start dev profile service in background
echo   dev-down    Stop dev profile service
echo   dev-logs    Tail dev profile logs
echo   dev-shell   Open shell in dev container
exit /b 1
