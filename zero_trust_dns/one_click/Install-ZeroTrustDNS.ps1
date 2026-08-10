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

$AghVersion = '0.107.78'
$AghZipUrl = "https://github.com/AdguardTeam/AdGuardHome/releases/download/v$AghVersion/AdGuardHome_windows_amd64.zip"
$AghZipSha256 = '481c8666b9ce8cd2ef12d4f758fcf07b40f7eb8a919a70e3355f15b5d84eddbe'

$Quad9Upstreams = @(
    'tls://dns.quad9.net',
    'https://dns.quad9.net/dns-query'
)
# Bootstrap is used only to resolve encrypted upstream hostnames.
$Quad9Bootstrap = @('9.9.9.9', '149.112.112.112')
$AdGuardDnsFilterUrl = 'https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt'

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
    param(
        [Parameter(Mandatory=$true)][string]$Uri,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$ExpectedSha256,
        [switch]$RequireAuthenticode
    )
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
    if ($existing) {
        Write-Log "Tailscale already installed: $existing"
        return $existing
    }

    $hashText = (Invoke-WebRequest -UseBasicParsing -Uri $TailscaleMsiHashUrl).Content
    $m = [regex]::Match($hashText, '(?i)\b[0-9a-f]{64}\b')
    if (-not $m.Success) { throw 'Could not parse the official Tailscale SHA-256 file.' }
    $expected = $m.Value.ToLowerInvariant()

    $msi = Join-Path $Downloads "tailscale-setup-$TailscaleVersion-amd64.msi"
    Get-RemoteFileVerified -Uri $TailscaleMsiUrl -Destination $msi -ExpectedSha256 $expected -RequireAuthenticode

    Write-Log "install Tailscale $TailscaleVersion"
    $proc = Start-Process -FilePath msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart" -Wait -PassThru
    if ($proc.ExitCode -notin @(0, 3010, 1641)) {
        throw "Tailscale MSI failed: exit=$($proc.ExitCode)"
    }

    Start-Sleep -Seconds 2
    $exe = Get-TailscaleExe
    if (-not $exe) { throw 'tailscale.exe was not found after MSI installation.' }
    return $exe
}

function Test-TailscaleIPv4 {
    param([string]$Ip)
    $parts = $Ip -split '\.'
    if ($parts.Count -ne 4) { return $false }
    if ([int]$parts[0] -ne 100) { return $false }
    $second = [int]$parts[1]
    return ($second -ge 64 -and $second -le 127)
}

function Connect-Tailscale {
    param([string]$TailscaleExe)

    $ip = (& $TailscaleExe ip -4 2>$null | Select-Object -First 1)
    if ($ip -and (Test-TailscaleIPv4 $ip.Trim())) {
        Write-Log "Tailscale already connected: $($ip.Trim())"
        & $TailscaleExe up --unattended=true | Out-Null
        & $TailscaleExe set --accept-dns=false | Out-Null
        return $ip.Trim()
    }

    Write-Log 'Tailscale authentication required.'
    if ($env:TS_AUTH_KEY) {
        Write-Log 'Using TS_AUTH_KEY from environment; value is never written to log.'
        & $TailscaleExe up "--auth-key=$($env:TS_AUTH_KEY)" --unattended=true --accept-dns=false
        $env:TS_AUTH_KEY = $null
    } else {
        Write-Host ''
        Write-Host 'Tailscale first-time authentication is required. Complete the browser/URL sign-in.' -ForegroundColor Yellow
        Write-Host 'The installer continues automatically after authentication.' -ForegroundColor Yellow
        Write-Host ''
        & $TailscaleExe up --unattended=true --accept-dns=false
    }

    for ($i = 0; $i -lt 90; $i++) {
        $ip = (& $TailscaleExe ip -4 2>$null | Select-Object -First 1)
        if ($ip -and (Test-TailscaleIPv4 $ip.Trim())) {
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

function Save-AdminCredential {
    param([string]$Username, [string]$Password)
    Set-Content -LiteralPath $AdminUserPath -Value $Username -Encoding UTF8
    $secure = ConvertTo-SecureString -String $Password -AsPlainText -Force
    $protected = ConvertFrom-SecureString -SecureString $secure
    Set-Content -LiteralPath $AdminSecretPath -Value $protected -Encoding ASCII
}

function Load-AdminCredential {
    if (-not (Test-Path -LiteralPath $AdminUserPath)) { return $null }
    if (-not (Test-Path -LiteralPath $AdminSecretPath)) { return $null }
    try {
        $u = (Get-Content -LiteralPath $AdminUserPath -Raw).Trim()
        $enc = (Get-Content -LiteralPath $AdminSecretPath -Raw).Trim()
        $secure = ConvertTo-SecureString -String $enc
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $p = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
        return @{ Username = $u; Password = $p }
    } catch {
        return $null
    }
}

function Get-BasicAuthHeader {
    param([string]$Username, [string]$Password)
    $raw = '{0}:{1}' -f $Username, $Password
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($raw))
    return @{ Authorization = "Basic $b64" }
}

function Invoke-AghApi {
    param(
        [string]$Method,
        [string]$Path,
        [hashtable]$Credential,
        $Body = $null
    )
    $params = @{
        Method = $Method
        Uri = "http://127.0.0.1:3001/control$Path"
        Headers = (Get-BasicAuthHeader -Username $Credential.Username -Password $Credential.Password)
    }
    if ($null -ne $Body) {
        $params['ContentType'] = 'application/json'
        $params['Body'] = ($Body | ConvertTo-Json -Depth 10 -Compress)
    }
    return Invoke-RestMethod @params
}

function Wait-Http {
    param([string]$Uri, [hashtable]$Headers = @{}, [int]$Seconds = 30)
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Uri -Headers $Headers -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Install-AdGuardHomeIfNeeded {
    param([string]$TailIp)

    $exe = Join-Path $AghInstall 'AdGuardHome.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        $zip = Join-Path $Downloads "AdGuardHome_windows_amd64-$AghVersion.zip"
        Get-RemoteFileVerified -Uri $AghZipUrl -Destination $zip -ExpectedSha256 $AghZipSha256

        $stage = Join-Path $Downloads 'agh-stage'
        Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $stage -Force | Out-Null
        Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
        $source = Join-Path $stage 'AdGuardHome'
        if (-not (Test-Path -LiteralPath (Join-Path $source 'AdGuardHome.exe'))) {
            throw 'AdGuard Home archive layout is unexpected.'
        }
        New-Item -ItemType Directory -Path $AghInstall -Force | Out-Null
        Copy-Item -Path (Join-Path $source '*') -Destination $AghInstall -Recurse -Force
        Write-Log "installed AdGuard Home files: v$AghVersion"
    }

    $versionText = (& $exe --version 2>&1 | Out-String)
    if ($versionText -notmatch [regex]::Escape("v$AghVersion")) {
        throw "AdGuard Home version mismatch: $versionText"
    }

    $configPath = Join-Path $AghWork 'AdGuardHome.yaml'
    $cred = Load-AdminCredential

    $svc = Get-Service -Name 'AdGuardHome' -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running' -and $cred) {
        Write-Log 'AdGuard Home service already running; re-applying policy.'
        return @{ Exe = $exe; Config = $configPath; Credential = $cred }
    }

    if ($svc -and $svc.Status -eq 'Running') {
        Stop-Service -Name 'AdGuardHome' -Force
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
    }

    if (-not (Test-Path -LiteralPath $configPath)) {
        $adminUser = 'zerotrustdns-admin'
        $adminPassword = New-RandomPassword

        Write-Log 'starting AdGuard Home installer on loopback only'
        $proc = Start-Process -FilePath $exe -ArgumentList "--no-check-update --web-addr 127.0.0.1:3000 -w `"$AghWork`"" -PassThru -WindowStyle Hidden
        try {
            if (-not (Wait-Http -Uri 'http://127.0.0.1:3000/control/install/get_addresses' -Seconds 30)) {
                throw 'AdGuard Home installer API did not become ready.'
            }

            $checkBody = @{
                web = @{ ip = '127.0.0.1'; port = 3001; autofix = $false }
                dns = @{ ip = $TailIp; port = 53; autofix = $false }
                set_static_ip = $false
                language = 'ja'
            }
            $check = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3000/control/install/check_config' -ContentType 'application/json' -Body ($checkBody | ConvertTo-Json -Depth 6 -Compress)
            foreach ($name in @('web','dns')) {
                if ($check.$name.status) { throw "AdGuard Home bind check failed ($name): $($check.$name.status)" }
            }

            $configureBody = @{
                web = @{ ip = '127.0.0.1'; port = 3001 }
                dns = @{ ip = $TailIp; port = 53 }
                username = $adminUser
                password = $adminPassword
                language = 'ja'
            }
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3000/control/install/configure' -ContentType 'application/json' -Body ($configureBody | ConvertTo-Json -Depth 6 -Compress) | Out-Null
            Save-AdminCredential -Username $adminUser -Password $adminPassword
            $cred = @{ Username = $adminUser; Password = $adminPassword }
            Write-Log 'AdGuard Home first configuration completed.'
        } finally {
            if (-not $proc.HasExited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Seconds 2
    } elseif (-not $cred) {
        throw 'Existing AdGuardHome.yaml found but local DPAPI admin credential is unavailable. Refusing to overwrite it.'
    }

    $svc = Get-Service -Name 'AdGuardHome' -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Log 'installing AdGuard Home Windows service'
        & $exe -s install --no-check-update -c $configPath -w $AghWork | Out-Null
    }
    & $exe -s start --no-check-update -c $configPath -w $AghWork | Out-Null
    Start-Sleep -Seconds 2

    return @{ Exe = $exe; Config = $configPath; Credential = $cred }
}

function Apply-AdGuardPolicy {
    param([hashtable]$Credential)

    $headers = Get-BasicAuthHeader -Username $Credential.Username -Password $Credential.Password
    if (-not (Wait-Http -Uri 'http://127.0.0.1:3001/control/status' -Headers $headers -Seconds 30)) {
        throw 'AdGuard Home control API is not reachable on loopback.'
    }

    $testBody = @{
        bootstrap_dns = $Quad9Bootstrap
        upstream_dns = $Quad9Upstreams
        fallback_dns = @()
        private_upstream = @()
    }
    $upstreamResult = Invoke-AghApi -Method Post -Path '/test_upstream_dns' -Credential $Credential -Body $testBody
    foreach ($p in $upstreamResult.PSObject.Properties) {
        if ($p.Value -ne 'OK') { throw "Upstream test failed: $($p.Name) => $($p.Value)" }
    }

    $dnsBody = @{
        upstream_dns = $Quad9Upstreams
        bootstrap_dns = $Quad9Bootstrap
        fallback_dns = @()
        protection_enabled = $true
        edns_cs_enabled = $false
        dnssec_enabled = $true
        upstream_mode = 'load_balance'
    }
    Invoke-AghApi -Method Post -Path '/dns_config' -Credential $Credential -Body $dnsBody | Out-Null

    $accessBody = @{
        allowed_clients = @('100.64.0.0/10', '127.0.0.1/32', '::1/128')
        disallowed_clients = @()
        blocked_hosts = @()
    }
    Invoke-AghApi -Method Post -Path '/access/set' -Credential $Credential -Body $accessBody | Out-Null

    Invoke-AghApi -Method Post -Path '/filtering/config' -Credential $Credential -Body @{ enabled = $true; interval = 24 } | Out-Null
    $filterStatus = Invoke-AghApi -Method Get -Path '/filtering/status' -Credential $Credential
    $hasOfficial = $false
    foreach ($f in @($filterStatus.filters)) {
        if ($f.url -eq $AdGuardDnsFilterUrl) { $hasOfficial = $true }
    }
    if (-not $hasOfficial) {
        Invoke-AghApi -Method Post -Path '/filtering/add_url' -Credential $Credential -Body @{
            name = 'AdGuard DNS filter'
            url = $AdGuardDnsFilterUrl
            whitelist = $false
        } | Out-Null
    }
    Invoke-AghApi -Method Post -Path '/filtering/refresh' -Credential $Credential -Body @{ whitelist = $false } | Out-Null
    Write-Log 'AdGuard Home policy applied.'
}

function Assert-NoWildcardListeners {
    $bad = @()
    $tcp = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
    foreach ($x in $tcp) {
        if ($x.LocalPort -in @(53, 3001) -and $x.LocalAddress -in @('0.0.0.0','::')) {
            $bad += "$($x.LocalAddress):$($x.LocalPort)/tcp"
        }
    }
    $udp = Get-NetUDPEndpoint -ErrorAction SilentlyContinue
    foreach ($x in $udp) {
        if ($x.LocalPort -eq 53 -and $x.LocalAddress -in @('0.0.0.0','::')) {
            $bad += "$($x.LocalAddress):53/udp"
        }
    }
    if ($bad.Count -gt 0) { throw "Wildcard listener detected: $($bad -join ', ')" }
}

function Verify-Dns {
    param([string]$TailIp)
    $result = Resolve-DnsName -Name 'example.com' -Server $TailIp -DnsOnly -Type A -ErrorAction Stop
    if (-not ($result | Where-Object { $_.Type -eq 'A' })) {
        throw 'DNS smoke test returned no A record.'
    }
    Write-Log 'DNS smoke test passed.'
}

function Write-Status {
    param([string]$TailIp, [string]$TailscaleExe)
    $tsVersion = (& $TailscaleExe version | Select-Object -First 1)
    $obj = [ordered]@{
        schema_version = 1
        timestamp = (Get-Date).ToUniversalTime().ToString('o')
        status = 'ready'
        tailscale_ip = $TailIp
        tailscale_version = $tsVersion
        adguard_home_version = $AghVersion
        adguard_home_windows_amd64_sha256 = $AghZipSha256
        normal_upstream_dns_encrypted = $true
        bootstrap_dns_limited_exception = $Quad9Bootstrap
        public_dns_listener = $false
        admin_public = $false
        dns_smoke_test = $true
        tailnet_dns_override = 'requires Tailscale admin-console configuration unless already configured'
    }
    $obj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StatusPath -Encoding UTF8
}

try {
    New-Item -ItemType Directory -Path $Root, $Downloads, $AghWork -Force | Out-Null
    if (Test-Path -LiteralPath $LogPath) {
        Add-Content -LiteralPath $LogPath -Value '' -Encoding UTF8
    }

    Assert-Administrator
    Assert-Platform
    Write-Log '=== ZeroTrustDNS one-click install start ==='

    $tailscale = Install-TailscaleIfNeeded
    $tailIp = Connect-Tailscale -TailscaleExe $tailscale

    $agh = Install-AdGuardHomeIfNeeded -TailIp $tailIp
    Apply-AdGuardPolicy -Credential $agh.Credential

    Assert-NoWildcardListeners
    Verify-Dns -TailIp $tailIp
    Write-Status -TailIp $tailIp -TailscaleExe $tailscale

    Write-Log '=== server-side setup READY ==='
    Write-Host ''
    Write-Host 'ZeroTrustDNS server-side setup is complete.' -ForegroundColor Green
    Write-Host "DNS server: $tailIp" -ForegroundColor Green
    Write-Host ''
    Write-Host 'To force this DNS across the tailnet, open the Tailscale DNS admin page and set:' -ForegroundColor Yellow
    Write-Host "Global nameserver = $tailIp, then enable Override DNS servers." -ForegroundColor Yellow
    Write-Host 'This is a Tailscale administrator control-plane action and is not silently changed by this installer.' -ForegroundColor Yellow

    Set-Clipboard -Value $tailIp -ErrorAction SilentlyContinue
    Start-Process 'https://login.tailscale.com/admin/dns'

    if (-not $NonInteractive) {
        Write-Host ''
        Read-Host 'Press Enter to close'
    }
    exit 0
} catch {
    try { Write-Log ("FAILED: " + $_.Exception.Message) } catch {}
    Write-Host ''
    Write-Host ('Setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Log: $LogPath" -ForegroundColor Red
    if (-not $NonInteractive) {
        Read-Host 'Press Enter to close'
    }
    exit 1
}
