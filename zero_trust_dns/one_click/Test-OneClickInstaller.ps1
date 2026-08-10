$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$installer = Join-Path $PSScriptRoot 'Install-ZeroTrustDNS.ps1'
$bootstrap = Join-Path (Split-Path -Parent $root) 'INSTALL-ZEROTRUST-DNS.cmd'

if (-not (Test-Path -LiteralPath $installer)) { throw 'installer missing' }
if (-not (Test-Path -LiteralPath $bootstrap)) { throw 'bootstrap missing' }

$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { Write-Error $_.Message }
    throw 'PowerShell parser errors detected'
}
Write-Host 'PASS syntax: installer parses'

$text = Get-Content -LiteralPath $installer -Raw
$compact = ($text -replace '\s+', '')
$cmd = Get-Content -LiteralPath $bootstrap -Raw

$requiredText = @(
    "`$TailscaleVersion = '1.102.2'",
    'https://pkgs.tailscale.com/stable/tailscale-setup-',
    "`$TailscaleHostname = 'zerotrust-dns'",
    "`$AghVersion = '0.107.78'",
    '481c8666b9ce8cd2ef12d4f758fcf07b40f7eb8a919a70e3355f15b5d84eddbe',
    'tls://dns.quad9.net',
    'https://dns.quad9.net/dns-query',
    "`$AndroidCanaryDomain = 'ready.zerotrustdns.test'",
    'Get-AuthenticodeSignature',
    'Get-FileHash -Algorithm SHA256',
    'ConvertFrom-SecureString',
    'Resolve-DnsName',
    'Assert-NoWildcardListeners',
    "'/rewrite/add'"
)
foreach ($needle in $requiredText) {
    if (-not $text.Contains($needle)) { throw "required safety contract missing: $needle" }
}

$requiredCompact = @(
    "allowed_clients=@('100.64.0.0/10','127.0.0.1/32','::1/128')",
    "web=@{ip='127.0.0.1';port=3001",
    "dns=@{ip=`$TailIp;port=53",
    '--accept-dns=false',
    '--hostname=$TailscaleHostname'
)
foreach ($needle in $requiredCompact) {
    if (-not $compact.Contains(($needle -replace '\s+',''))) { throw "required compact contract missing: $needle" }
}
Write-Host 'PASS contract: required Windows + Android safety controls present'

$forbiddenPatterns = @(
    "web\s*=\s*@\{\s*ip\s*=\s*'0\.0\.0\.0'",
    "dns\s*=\s*@\{\s*ip\s*=\s*'0\.0\.0\.0'",
    "web\s*=\s*@\{\s*ip\s*=\s*'::'",
    "dns\s*=\s*@\{\s*ip\s*=\s*'::'",
    'http://dns\.quad9\.net',
    'udp://dns\.quad9\.net'
)
foreach ($pattern in $forbiddenPatterns) {
    if ($text -match $pattern) { throw "unsafe contract present: $pattern" }
}
Write-Host 'PASS contract: no public/wildcard target bind or plaintext normal upstream'

if ($text -match '(?im)Write-(Host|Log).*\$env:TS_AUTH_KEY') {
    throw 'auth key could be written to output/log'
}
Write-Host 'PASS secret handling: TS_AUTH_KEY not logged'

if ($cmd -notmatch 'PAYLOAD_COMMIT=[0-9a-f]{40}') { throw 'bootstrap payload is not commit pinned' }
if ($cmd -notmatch 'https://raw\.githubusercontent\.com/KAFKA2306/BestEthernet/%PAYLOAD_COMMIT%/') { throw 'bootstrap source is not pinned GitHub Raw path' }
if ($cmd -notmatch '-Verb RunAs') { throw 'bootstrap does not request UAC elevation' }
Write-Host 'PASS bootstrap: immutable payload ref + UAC entrypoint'

Write-Host 'ALL ONE-CLICK STATIC TESTS PASSED'
