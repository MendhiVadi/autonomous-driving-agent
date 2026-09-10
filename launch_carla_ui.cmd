@echo off
setlocal enabledelayedexpansion

rem ---------------------------------------------------------------------
rem Entry point for the CARLA + neural-driver stack. No gesture/webcam/visual
rem engine is started here - this is CARLA plus the car that drives itself.
rem
rem This used to fire processes into detached Scheduled Tasks with no logging
rem and no supervision. On 2026-09-09 a component wedged, Windows killed it as
rem a hung application, and the whole stack stayed down with nothing written
rem down anywhere. Now this script does two things only:
rem   1. refuse to launch straight back into a thermal or hardware fault, and
rem   2. start ONE detached supervisor that owns, logs, probes, and restarts
rem      the components.
rem Everything else lives in stack_supervisor.py, where it can be tested.
rem ---------------------------------------------------------------------

if not defined CARLA_ROOT set "CARLA_ROOT=C:\Users\medha\Documents\CARLA\CARLA_0.9.16"
set "APP_ROOT=%~dp0"
for %%I in ("%~dp0.") do set "APP_ROOT_TASK=%%~fI"
set "CARLA_PYTHON=%CARLA_ROOT%\carla_env\Scripts\python.exe"
set "LOG_DIR=%APP_ROOT%logs"
set "EXTRA_ARGS="

rem --force skips the thermal cooldown check; --opengl picks the cooler renderer.
:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--force" set "EXTRA_ARGS=!EXTRA_ARGS! --no-thermal-guard"
if /I "%~1"=="--opengl" set "EXTRA_ARGS=!EXTRA_ARGS! --render-api opengl"
shift
goto parse_args
:args_done

if not exist "%CARLA_ROOT%\CarlaUE4.exe" (
    echo ERROR: CARLA server was not found at "%CARLA_ROOT%\CarlaUE4.exe".
    pause
    exit /b 1
)
if not exist "%CARLA_PYTHON%" (
    echo ERROR: CARLA Python environment was not found.
    pause
    exit /b 1
)
if not exist "%APP_ROOT%nn_policy_colab.json" (
    echo ERROR: deployable route-conditioned policy was not found:
    echo   "%APP_ROOT%nn_policy_colab.json"
    echo.
    echo The lightweight runtime will not start with the legacy or smoke-test
    echo policy. Train and export the real Colab policy first, then copy it to
    echo that exact path.
    pause
    exit /b 1
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

rem ---------------------------------------------------------------------
rem Thermal / hardware preflight. This laptop has an Intel Arc 140V iGPU and
rem no discrete card, so CARLA's renderer shares its thermal package with the
rem CPU. It has already hibernated itself under this load once.
rem ---------------------------------------------------------------------
echo Checking for recent thermal or hardware faults...
echo %EXTRA_ARGS% | find "--no-thermal-guard" >NUL
if errorlevel 1 (
    "%CARLA_PYTHON%" "%APP_ROOT%health_guard.py"
    if errorlevel 1 (
        echo.
        echo REFUSING TO LAUNCH. The machine reported a thermal or hardware fault
        echo recently and is still inside its cooldown window. Let it cool, or
        echo re-run with --force if you accept the risk of another hard crash.
        pause
        exit /b 1
    )
) else (
    echo Skipped: --force was given.
)

rem Already supervised? Don't start a second one.
powershell.exe -NoProfile -Command "if(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'stack_supervisor\.py' }){exit 0}else{exit 1}"
if not errorlevel 1 (
    echo The stack supervisor is already running.
    echo Status: "%LOG_DIR%\stack_status.json"
    echo Stop it with stop_stack.cmd
    exit /b 0
)

rem A leftover status file from a previous run already satisfies the
rem readiness check below, so the wait loop can report READY instantly
rem without the new supervisor having started anything. Clear it first so
rem READY only ever comes from a fresh write by the process we are about
rem to start.
if exist "%LOG_DIR%\stack_status.json" del /f /q "%LOG_DIR%\stack_status.json"

echo Starting the supervised stack...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_ROOT%start_stack_supervisor.ps1" ^
    -PythonPath "%CARLA_PYTHON%" -AppRoot "%APP_ROOT_TASK%" -CarlaRoot "%CARLA_ROOT%" ^
    -LogDir "%LOG_DIR%" -SupervisorExtraArgs "!EXTRA_ARGS!"
if errorlevel 1 (
    echo ERROR: the supervisor process did not start.
    exit /b 1
)

rem The supervisor brings CARLA up first; the software renderer needs a while.
echo Waiting for the stack to report ready (up to 180s)...
powershell.exe -NoProfile -Command "$deadline=(Get-Date).AddSeconds(180); $status='%LOG_DIR%\stack_status.json'; while((Get-Date) -lt $deadline){ if(Test-Path $status){ try{ $s = Get-Content $status -Raw | ConvertFrom-Json; if($s.components.carla.ready -and $s.components.neural.ready){ exit 0 } if($s.thermal_hold){ Write-Host \"  holding: $($s.thermal_hold)\" } }catch{} } Start-Sleep -Seconds 3 }; exit 1"
if errorlevel 1 (
    echo.
    echo WARNING: the stack did not report ready within 180 seconds.
    echo The supervisor is still running and will keep retrying.
    echo Check the logs:
    echo   "%LOG_DIR%\supervisor.log"
    echo   "%LOG_DIR%\carla.log"
    echo   "%LOG_DIR%\neural.log"
    pause
    exit /b 1
)

echo.
echo READY: CARLA is off-screen and the neural car is driving itself.
echo No gesture/webcam engine and no cockpit window are loaded.
echo.
echo The supervisor restarts any component that dies or stops responding, and
echo holds off launching while the machine is recovering from a thermal fault.
echo   Live status : "%LOG_DIR%\stack_status.json"
echo   Logs        : "%LOG_DIR%"
echo   Stop it with: stop_stack.cmd
echo.
echo The supervisor runs as a detached Scheduled Task and keeps running even if
echo this window or whatever launched it (including an AI agent) closes.

endlocal
exit /b 0
