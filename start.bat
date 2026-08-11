@echo off
setlocal enabledelayedexpansion
title Review Platform - One-click Start
cd /d "%~dp0"

echo ==============================================
echo   Internal Review Platform - One-click Start
echo ==============================================
echo.

REM -- step 0: check .env --
if not exist ".env" (
    echo [WARN] .env not found. Defaults will be used - email service disabled.
    echo        Copy .env.example to .env and fill in SMTP config first.
    echo.
)

REM -- step 1: detect campus IP and sync .env SITE_BASE_URL --
echo [0/4] Detecting campus network IP...
set "CAMPUS_IP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '0.0.0.0' } | Sort-Object @{Expression={$_.InterfaceAlias -match 'ZeroTier|Virtual|vEthernet|WSL|Loopback'}} | Select-Object -First 1 -ExpandProperty IPAddress"`) do set "CAMPUS_IP=%%i"
if defined CAMPUS_IP (
    echo [OK] Current IP: %CAMPUS_IP%
    if exist ".env" (
        powershell -NoProfile -Command "$p='.env'; $t=[System.IO.File]::ReadAllText($p) -replace '(?m)^SITE_BASE_URL=.*$', 'SITE_BASE_URL=http://%CAMPUS_IP%:8000'; [System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding $false))"
        echo [OK] .env SITE_BASE_URL synced to http://%CAMPUS_IP%:8000
    )
) else (
    echo [WARN] No network IP detected, SITE_BASE_URL left unchanged.
)
echo.

REM -- step 2: check Docker --
where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker not found. Please install and start Docker Desktop first.
    pause
    exit /b 1
)

REM -- step 3: wait for Docker engine --
echo [1/4] Checking Docker engine...
docker info >nul 2>nul
if errorlevel 1 (
    echo [INFO] Docker engine not ready, trying to open Docker Desktop...
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        echo [INFO] Docker Desktop.exe not found. Please open Docker Desktop manually.
    )
    set /a _n=0
    :wait_docker
    set /a _n+=1
    if !_n! gtr 60 (
        echo [ERROR] Timeout waiting for Docker 60s. Open Docker Desktop manually and retry.
        pause
        exit /b 1
    )
    timeout /t 2 /nobreak >nul
    docker info >nul 2>nul
    if errorlevel 1 goto wait_docker
)
echo [OK] Docker is ready
echo.

REM -- step 4: build and start - with retries for flaky networks --
echo [2/4] Cleaning stale containers, then building and starting services...
docker compose down --remove-orphans >nul 2>nul
set /a _try=0
:build_retry
set /a _try+=1
docker compose up -d --build
if errorlevel 1 (
    if !_try! lss 3 (
        echo [WARN] Build failed on attempt !_try!/3 - retrying in 3s. Usually a temporary Docker Hub network issue.
        timeout /t 3 /nobreak >nul
        goto build_retry
    )
    echo.
    echo [ERROR] Failed to start services after 3 attempts. Check the log above.
    echo        Tip: configure a Docker Hub mirror in Docker Desktop - Settings - Docker Engine.
    pause
    exit /b 1
)
echo.

REM -- step 5: wait for health --
echo [3/4] Waiting for service to be ready...
set /a _n=0
:wait_svc
set /a _n+=1
if !_n! gtr 120 goto show_url
timeout /t 1 /nobreak >nul
where curl >nul 2>nul
if errorlevel 1 goto show_url
curl -s -f -o nul http://127.0.0.1:8000/health
if errorlevel 1 goto wait_svc

REM -- step 6: show access URLs --
:show_url
echo [4/4] Service is up!
echo.
echo   Local access:   http://localhost:8000
echo   --------------------------------------------------
echo   Others - campus network or VPN - can open:
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '0.0.0.0' } | Select-Object -ExpandProperty IPAddress"`) do (
    echo      http://%%i:8000
)
echo   --------------------------------------------------
echo.
echo   Note 1: If others cannot connect, run as ADMIN:
echo           New-NetFirewallRule -DisplayName "Review-8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
echo   Note 2: Closing this window does NOT stop the server.
echo           To stop:  docker compose down
echo   Note 3: SITE_BASE_URL is auto-updated to the current IP on every start.
echo.
start "" http://localhost:8000
pause
