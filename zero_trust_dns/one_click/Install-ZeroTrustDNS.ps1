#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ProductName = 'ZeroTrustDNS'
$Root = Join-Path $env:ProgramData $ProductName
$Downloads = Join-Path $Root 'downloads'
$AghWork = Join-Path $Root 'AdGuardHome'
$AghInstall = Join-Path $env:ProgramFiles "$ProductName\AdGuardHome"
$LogPath = Join-Path $Root 'install.log'
$StatusPath = Join-Path $Root 'status.json'
$AdminUserPath = Join-Path $Root 'admin-username.txt'
$AdminSecretPath = Join-Path $Root 'admin-password.dpapi'

$TailscaleVersion = '1.102.2'
$TailscaleMsiUrl = "https://pkgs.tailscale.com/stable/tailscale-setup-$TailscaleVersion-amd64.msi"
$TailscaleMsiHashUrl = "$TailscaleMsiUrl.sha256"
$TailscaleHostname = 'zerotrust-dns'

$AghVersion = '0.107.78'
$AghZipUrl = "https://github.com/AdguardTeam/AdGuardHome/releases/download/v$AghVersion/AdGuardHome_windows_amd64.zip"
$AghZipSha256 = '481c8666b9ce8cd2ef12d4f758fcf07b40f7eb8a919a70e3355f15b5d84eddbe'

$Quad9Upstreams = @(
    'tls://dns.quad9.net',
    'https://dns.quad9.net/dns-query'
)
$Quad9Bootstrap = @('9.9.9.9', '149.112.112.112')
$AdGuardDnsFilterUrl = 'https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt'
$AndroidCanaryDomain = 'ready.zerotrustdns.test'

function Write-Log {
    param([string]$Message)
    $line = '[{0}] {1}' -f (Get-Date).ToString('s'), $Message
    Write-Host $line
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Administrator privileges are required. Run Install-ZeroTrustDNS.cmd.'
    }
}

function Assert-Platform {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'This installer supports 64-bit Windows (amd64) only.'
    }
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -notin @('AMD64', 'x86')) {
        throw "This installer supports amd64 Windows only. Detected: $arch"
    }
}

function Get-RemoteFileVerified {
    param([string]$Uri,[string]$Destination,[string]$ExpectedSha256,[switch]$RequireAuthenticode)
    Write-Log "download: $Uri"
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $Destination
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Destination).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
        throw "SHA-256 mismatch: $Destination"
    }
    if ($RequireAuthenticode) {
        $sig = Get-AuthenticodeSignature -FilePath $Destination
        if ($sig.Status -ne 'Valid') {
            Remove-Item -LiteralPath $Destination -Force -ErrorAction SilentlyContinue
            throw "Authenticode signature is not valid: $($sig.Status)"
        }
    }
    Write-Log "verified sha256: $actual"
}

function Get-TailscaleExe {
    $cmd = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidate = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

function Install-TailscaleIfNeeded {
    $existing = Get-TailscaleExe
    if ($existing) { Write-Log "Tailscale already installed: $existing"; return $existing }
    $hashText = (Invoke-WebRequest -UseBasicParsing -Uri $TailscaleMsiHashUrl).Content
    $m = [regex]::Match($hashText, '(?i)\b[0-9a-f]{64}\b')
    if (-not $m.Success) { throw 'Could not parse the official Tailscale SHA-256 file.' }
    $msi = Join-Path $Downloads "tailscale-setup-$TailscaleVersion-amd64.msi"
    Get-RemoteFileVerified -Uri $TailscaleMsiUrl -Destination $msi -ExpectedSha256 $m.Value -RequireAuthenticode
    $proc = Start-Process -FilePath msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait -PassThru
    if ($proc.ExitCode -notin @(0,3010,1641)) { throw "Tailscale MSI failed: exit=$($proc.ExitCode)" }
    Start-Sleep -Seconds 2
    $exe = Get-TailscaleExe
    if (-not $exe) { throw 'tailscale.exe was not found after MSI installation.' }
    return $exe
}

function Test-TailscaleIPv4 {
    param([string]$Ip)
    $parts = $Ip -split '\.'
    if ($parts.Count -ne 4 -or [int]$parts[0] -ne 100) { return $false }
    $second = [int]$parts[1]
    return ($second -ge 64 -and $second -le 127)
}

function Connect-Tailscale {
    param([string]$TailscaleExe)
    $ip = (& $TailscaleExe ip -4 2>$null | Select-Object -First 1)
    if ($ip -and (Test-TailscaleIPv4 $ip.Trim())) {
        & $TailscaleExe set --accept-dns=false --hostname=$TailscaleHostname | Out-Null
        Write-Log "Tailscale already connected: $($ip.Trim())"
        return $ip.Trim()
    }
    Write-Log 'Tailscale authentication required.'
    if ($env:TS_AUTH_KEY) {
        Write-Log 'Using TS_AUTH_KEY from environment; value is never written to log.'
        & $TailscaleExe up "--auth-key=$($env:TS_AUTH_KEY)" --unattended=true --accept-dns=false --hostname=$TailscaleHostname
        $env:TS_AUTH_KEY = $null
    } else {
        Write-Host 'Tailscale first-time authentication is required. Complete the browser/URL sign-in.' -ForegroundColor Yellow
        & $TailscaleExe up --unattended=true --accept-dns=false --hostname=$TailscaleHostname
    }
    for ($i=0; $i -lt 90; $i++) {
        $ip = (& $TailscaleExe ip -4 2>$null | Select-Object -First 1)
        if ($ip -and (Test-TailscaleIPv4 $ip.Trim())) {
            & $TailscaleExe set --accept-dns=false --hostname=$TailscaleHostname | Out-Null
            Write-Log "Tailscale connected: $($ip.Trim())"
            return $ip.Trim()
        }
        Start-Sleep -Seconds 2
    }
    throw 'Could not obtain a Tailscale IPv4 address in 100.64.0.0/10.'
}

function New-RandomPassword {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_'))
}
function Save-AdminCredential { param([string]$Username,[string]$Password); Set-Content $AdminUserPath $Username -Encoding UTF8; $s=ConvertTo-SecureString $Password -AsPlainText -Force; Set-Content $AdminSecretPath (ConvertFrom-SecureString $s) -Encoding ASCII }
function Load-AdminCredential {
    if (-not (Test-Path $AdminUserPath) -or -not (Test-Path $AdminSecretPath)) { return $null }
    try { $u=(Get-Content $AdminUserPath -Raw).Trim(); $s=ConvertTo-SecureString ((Get-Content $AdminSecretPath -Raw).Trim()); $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try {$plain=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}; return @{Username=$u;Password=$plain} } catch { return $null }
}
function Get-BasicAuthHeader { param([string]$Username,[string]$Password); $b=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$Username`:$Password")); return @{Authorization="Basic $b"} }
function Invoke-AghApi { param([string]$Method,[string]$Path,[hashtable]$Credential,$Body=$null); $p=@{Method=$Method;Uri="http://127.0.0.1:3001/control$Path";Headers=(Get-BasicAuthHeader $Credential.Username $Credential.Password)}; if($null-ne $Body){$p.ContentType='application/json';$p.Body=($Body|ConvertTo-Json -Depth 10 -Compress)}; Invoke-RestMethod @p }
function Wait-Http { param([string]$Uri,[hashtable]$Headers=@{},[int]$Seconds=30); for($i=0;$i-lt$Seconds;$i++){try{Invoke-WebRequest -UseBasicParsing -Uri $Uri -Headers $Headers -TimeoutSec 2|Out-Null;return $true}catch{Start-Sleep 1}};return $false }

function Install-AdGuardHomeIfNeeded {
    param([string]$TailIp)
    $exe=Join-Path $AghInstall 'AdGuardHome.exe'
    if(-not(Test-Path $exe)){
        $zip=Join-Path $Downloads "AdGuardHome_windows_amd64-$AghVersion.zip"; Get-RemoteFileVerified $AghZipUrl $zip $AghZipSha256
        $stage=Join-Path $Downloads 'agh-stage'; Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory $stage -Force|Out-Null; Expand-Archive $zip $stage -Force
        $src=Join-Path $stage 'AdGuardHome'; if(-not(Test-Path (Join-Path $src 'AdGuardHome.exe'))){throw 'AdGuard Home archive layout is unexpected.'}; New-Item -ItemType Directory $AghInstall -Force|Out-Null; Copy-Item (Join-Path $src '*') $AghInstall -Recurse -Force
    }
    if((& $exe --version 2>&1|Out-String)-notmatch[regex]::Escape("v$AghVersion")){throw 'AdGuard Home version mismatch.'}
    $config=Join-Path $AghWork 'AdGuardHome.yaml'; $cred=Load-AdminCredential; $svc=Get-Service AdGuardHome -ErrorAction SilentlyContinue
    if($svc-and$svc.Status-eq'Running'-and$cred){return @{Exe=$exe;Config=$config;Credential=$cred}}
    if($svc-and$svc.Status-eq'Running'){Stop-Service AdGuardHome -Force}
    if(-not(Test-Path $config)){
        $user='zerotrustdns-admin';$pass=New-RandomPassword; $proc=Start-Process $exe -ArgumentList "--no-check-update --web-addr 127.0.0.1:3000 -w `"$AghWork`"" -PassThru -WindowStyle Hidden
        try{
            if(-not(Wait-Http 'http://127.0.0.1:3000/control/install/get_addresses')){throw 'AdGuard Home installer API did not become ready.'}
            $check=@{web=@{ip='127.0.0.1';port=3001;autofix=$false};dns=@{ip=$TailIp;port=53;autofix=$false};set_static_ip=$false;language='ja'}
            $r=Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3000/control/install/check_config' -ContentType 'application/json' -Body ($check|ConvertTo-Json -Depth 6 -Compress); if($r.web.status-or$r.dns.status){throw 'AdGuard Home bind check failed.'}
            $cfg=@{web=@{ip='127.0.0.1';port=3001};dns=@{ip=$TailIp;port=53};username=$user;password=$pass;language='ja'}
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3000/control/install/configure' -ContentType 'application/json' -Body ($cfg|ConvertTo-Json -Depth 6 -Compress)|Out-Null; Save-AdminCredential $user $pass; $cred=@{Username=$user;Password=$pass}
        } finally {if(-not$proc.HasExited){Stop-Process $proc.Id -Force -ErrorAction SilentlyContinue}}
    } elseif(-not$cred){throw 'Existing config found without local DPAPI credential; refusing overwrite.'}
    if(-not(Get-Service AdGuardHome -ErrorAction SilentlyContinue)){& $exe -s install --no-check-update -c $config -w $AghWork|Out-Null}; & $exe -s start --no-check-update -c $config -w $AghWork|Out-Null; Start-Sleep 2
    return @{Exe=$exe;Config=$config;Credential=$cred}
}

function Apply-AdGuardPolicy {
    param([hashtable]$Credential,[string]$TailIp)
    $h=Get-BasicAuthHeader $Credential.Username $Credential.Password; if(-not(Wait-Http 'http://127.0.0.1:3001/control/status' $h)){throw 'AdGuard Home control API unavailable.'}
    $test=@{bootstrap_dns=$Quad9Bootstrap;upstream_dns=$Quad9Upstreams;fallback_dns=@();private_upstream=@()}; $u=Invoke-AghApi Post '/test_upstream_dns' $Credential $test; foreach($p in $u.PSObject.Properties){if($p.Value-ne'OK'){throw "Upstream test failed: $($p.Name)"}}
    Invoke-AghApi Post '/dns_config' $Credential @{upstream_dns=$Quad9Upstreams;bootstrap_dns=$Quad9Bootstrap;fallback_dns=@();protection_enabled=$true;edns_cs_enabled=$false;dnssec_enabled=$true;upstream_mode='load_balance'}|Out-Null
    Invoke-AghApi Post '/access/set' $Credential @{allowed_clients=@('100.64.0.0/10','127.0.0.1/32','::1/128');disallowed_clients=@();blocked_hosts=@()}|Out-Null
    Invoke-AghApi Post '/filtering/config' $Credential @{enabled=$true;interval=24}|Out-Null
    $fs=Invoke-AghApi Get '/filtering/status' $Credential; if(-not(@($fs.filters)|Where-Object{$_.url-eq$AdGuardDnsFilterUrl})){Invoke-AghApi Post '/filtering/add_url' $Credential @{name='AdGuard DNS filter';url=$AdGuardDnsFilterUrl;whitelist=$false}|Out-Null}; Invoke-AghApi Post '/filtering/refresh' $Credential @{whitelist=$false}|Out-Null
    $rewrites=Invoke-AghApi Get '/rewrite/list' $Credential; $existing=@($rewrites)|Where-Object{$_.domain-eq$AndroidCanaryDomain}; foreach($e in $existing){if($e.answer-ne$TailIp){Invoke-AghApi Post '/rewrite/delete' $Credential @{domain=$e.domain;answer=$e.answer}|Out-Null}}
    $rewrites=Invoke-AghApi Get '/rewrite/list' $Credential; if(-not(@($rewrites)|Where-Object{$_.domain-eq$AndroidCanaryDomain-and$_.answer-eq$TailIp})){Invoke-AghApi Post '/rewrite/add' $Credential @{domain=$AndroidCanaryDomain;answer=$TailIp;enabled=$true}|Out-Null}
    Write-Log "Android DNS canary: $AndroidCanaryDomain -> $TailIp"
}

function Assert-NoWildcardListeners { $bad=@(); Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue|ForEach-Object{if($_.LocalPort-in@(53,3001)-and$_.LocalAddress-in@('0.0.0.0','::')){$bad+="$($_.LocalAddress):$($_.LocalPort)/tcp"}}; Get-NetUDPEndpoint -ErrorAction SilentlyContinue|ForEach-Object{if($_.LocalPort-eq53-and$_.LocalAddress-in@('0.0.0.0','::')){$bad+="$($_.LocalAddress):53/udp"}}; if($bad){throw "Wildcard listener: $($bad-join', ')"} }
function Verify-Dns { param([string]$TailIp); if(-not(Resolve-DnsName example.com -Server $TailIp -DnsOnly -Type A -ErrorAction Stop|Where-Object{$_.Type-eq'A'})){throw 'DNS smoke failed'}; $c=Resolve-DnsName $AndroidCanaryDomain -Server $TailIp -DnsOnly -Type A -ErrorAction Stop|Where-Object{$_.IPAddress-eq$TailIp}; if(-not$c){throw 'Android canary DNS smoke failed'}; Write-Log 'DNS smoke + Android canary passed.' }
function Write-Status { param([string]$TailIp,[string]$TailscaleExe); [ordered]@{schema_version=1;timestamp=(Get-Date).ToUniversalTime().ToString('o');status='ready';tailscale_ip=$TailIp;tailscale_hostname=$TailscaleHostname;tailscale_version=(& $TailscaleExe version|Select-Object -First 1);adguard_home_version=$AghVersion;android_canary=$AndroidCanaryDomain;normal_upstream_dns_encrypted=$true;bootstrap_dns_limited_exception=$Quad9Bootstrap;public_dns_listener=$false;admin_public=$false;dns_smoke_test=$true}|ConvertTo-Json|Set-Content $StatusPath -Encoding UTF8 }

try{
    New-Item -ItemType Directory $Root,$Downloads,$AghWork -Force|Out-Null; Assert-Administrator; Assert-Platform; Write-Log '=== ZeroTrustDNS one-click install start ==='
    $tailscale=Install-TailscaleIfNeeded; $tailIp=Connect-Tailscale $tailscale; $agh=Install-AdGuardHomeIfNeeded $tailIp; Apply-AdGuardPolicy $agh.Credential $tailIp; Assert-NoWildcardListeners; Verify-Dns $tailIp; Write-Status $tailIp $tailscale
    Write-Log '=== server-side setup READY ==='; Write-Host "DNS server: $tailIp" -ForegroundColor Green; Write-Host "Android canary: $AndroidCanaryDomain" -ForegroundColor Green; Set-Clipboard $tailIp -ErrorAction SilentlyContinue; Start-Process 'https://login.tailscale.com/admin/dns'; if(-not$NonInteractive){Read-Host 'Press Enter to close'}; exit 0
}catch{try{Write-Log("FAILED: "+$_.Exception.Message)}catch{};Write-Host('Setup failed: '+$_.Exception.Message)-ForegroundColor Red;Write-Host "Log: $LogPath";if(-not$NonInteractive){Read-Host 'Press Enter to close'};exit 1}
