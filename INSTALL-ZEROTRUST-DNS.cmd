@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PAYLOAD_COMMIT=9242891dbc88e9a7fd720f1604d7e8fab99cebb4"
set "PAYLOAD_URL=https://raw.githubusercontent.com/KAFKA2306/BestEthernet/%PAYLOAD_COMMIT%/zero_trust_dns/one_click/Install-ZeroTrustDNS.ps1"
set "PAYLOAD=%TEMP%\ZeroTrustDNS-Install-%PAYLOAD_COMMIT%.ps1"

echo [ZeroTrustDNS] 検証済みインストーラを取得しています...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%PAYLOAD_URL%' -OutFile '%PAYLOAD%'"
if errorlevel 1 goto :fail

echo [ZeroTrustDNS] 管理者権限でセットアップを開始します。UACで「はい」を選択してください。
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%PAYLOAD%""' -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
if errorlevel 1 goto :fail

del /q "%PAYLOAD%" >nul 2>&1
echo [ZeroTrustDNS] 完了しました。
exit /b 0

:fail
echo [ZeroTrustDNS] セットアップに失敗しました。
echo 詳細ログ: %%ProgramData%%\ZeroTrustDNS\install.log
pause
exit /b 1
