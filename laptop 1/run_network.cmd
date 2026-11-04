@echo off
setlocal
if "%~2"=="" (
    echo Usage: run_network.cmd PRIMARY_IP SECONDARY_IP
    echo Uses encrypted port 8765 and the locally generated pairing credentials.
    exit /b 2
)
call "%~dp0run_gateway.cmd" -Tls -GatewayBind "%~1" -PeerAddress "%~2"
exit /b %ERRORLEVEL%
