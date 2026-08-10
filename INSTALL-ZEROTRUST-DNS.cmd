@echo off
setlocal EnableExtensions

set "PAYLOAD_COMMIT=13b0dd9a6cea87bbd341e8c4e857060b60ab6883"
set "PAYLOAD_URL=https://raw.githubusercontent.com/KAFKA2306/BestEthernet/%PAYLOAD_COMMIT%/zero_trust_dns/one_click/Install-ZeroTrustDNS.ps1"
set "PAYLOAD=%TEMP%\ZeroTrustDNS-Install-%PAYLOAD_COMMIT%.ps1"

echo [ZeroTrustDNS] Downloading the reviewed commit-pinned installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PAYLOAD_URL%' -OutFile '%PAYLOAD%'"
if errorlevel 1 goto :fail

echo [ZeroTrustDNS] Starting elevated setup. Approve the Windows UAC prompt.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%PAYLOAD%""' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto :fail

del /q "%PAYLOAD%" >nul 2>&1
echo [ZeroTrustDNS] Completed.
exit /b 0

:fail
echo [ZeroTrustDNS] Setup failed.
echo Log: %%ProgramData%%\ZeroTrustDNS\install.log
pause
exit /b 1
