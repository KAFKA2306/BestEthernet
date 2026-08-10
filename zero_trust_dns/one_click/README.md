# ZeroTrustDNS — Windows ワンクリック入口

## 入口

Windows 10/11 amd64 では、リポジトリ直下の **`INSTALL-ZEROTRUST-DNS.cmd` をダブルクリック**します。

この1つの入口から、以下を自動実行します。

1. commit SHAで固定されたPowerShell installerをGitHub Rawから取得
2. UACで管理者権限へ昇格
3. Tailscaleが無ければ公式MSIを取得し、公式`.sha256`との一致とAuthenticode署名を検証して導入
4. Tailscaleをunattended modeへ設定
5. 未認証ならTailscale初回認証へ移行。`TS_AUTH_KEY`がある場合はブラウザ認証を省略可能
6. DNSホスト自身は`accept-dns=false`にし、tailnet DNSの自己参照ループを避ける
7. AdGuard Home v0.107.78 Windows amd64を公式releaseから取得し、固定SHA-256を検証
8. AdGuard Home管理UIを`127.0.0.1:3001`だけへbind
9. DNS listenerを、そのPCのTailscale `100.64.0.0/10`アドレスだけへbind
10. 通常upstreamをQuad9 SecureのDoT/DoHへ固定
11. ECSを無効化し、DNSSEC DOを有効化
12. `allowed_clients`をTailscale CGNAT + loopbackだけに固定
13. AdGuard DNS filterを有効化・更新
14. wildcard listenerが無いことを確認
15. `Resolve-DnsName`で実DNS疎通テスト
16. `%ProgramData%\ZeroTrustDNS\status.json`へsecretを含まない結果を保存

## 人間操作が残る境界

「ワンクリック」は**Windows DNSホストの構築**についてです。次は外部identity/control-planeのため、勝手に迂回しません。

- **UAC**: OSの権限昇格確認
- **Tailscale初回認証**: 事前に`TS_AUTH_KEY`を環境変数で渡していない場合のみ
- **tailnet全体のDNS強制**: Tailscale Admin Consoleで、このDNSホストの`100.x.y.z`をGlobal nameserverに設定し、`Override DNS servers`を有効化する管理者操作
- **Android初回参加**: Tailscaleアプリのインストール、identity認証、Android VPN同意

Tailscaleの公式仕様では、`Override DNS servers`を有効化するとtailnet端末はローカルDNSよりtailnetのGlobal nameserverを優先して常用します。したがってAndroidまで含めて完全に自動化したと主張するのは、この管理者設定とAndroid初回VPN同意まで実測してからです。

## セキュリティ境界

- `INSTALL-ZEROTRUST-DNS.cmd`が取得するpayloadは**branch名ではなく40桁commit SHA固定**
- Tailscale MSIは公式`.sha256`とWindows Authenticodeの両方を検証
- AdGuard Home ZIPは公式releaseのSHA-256に固定
- AdGuard Home管理passwordはランダム生成し、平文ファイルではなくWindows DPAPIでローカル保存
- `TS_AUTH_KEY`の値はログへ出力しない
- 通常DNS upstreamはDoT/DoHのみ
- Quad9の`9.9.9.9` / `149.112.112.112`は、暗号化upstream hostnameを最初に解決する**bootstrap専用の限定例外**として明示
- public DNS bind / public admin bindはfail-close

## CI

`ZeroTrustDNS one-click proof`はWindows GitHub runner上で以下を毎回検証します。

- PowerShell構文
- fail-closed静的契約
- bootstrapがimmutable commitに固定され、review対象installerとbyte一致すること
- Tailscale公式MSIのSHA-256 + Authenticode
- AdGuard Home公式Windows ZIPのSHA-256 + executable version

共有GitHub runnerへTailscale/AdGuard Homeを実インストールしてネットワークを書き換えることはしません。実機E2Eは別gateです。

## 一次情報

- Tailscale Windows MSI: https://tailscale.com/kb/1189/install-windows-msi/
- Tailscale stable packages: https://pkgs.tailscale.com/stable/
- Tailscale CLI / unattended: https://tailscale.com/docs/reference/tailscale-cli / https://tailscale.com/docs/how-to/run-unattended
- Tailscale DNS override: https://tailscale.com/docs/reference/dns-in-tailscale
- Tailscale auth-key handling: https://tailscale.com/docs/features/access-control/auth-keys/how-to/secure-auth-keys
- AdGuard Home releases: https://github.com/AdguardTeam/AdGuardHome/releases
- AdGuard Home configuration: https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration
- AdGuard Home API: https://github.com/AdguardTeam/AdGuardHome/blob/master/openapi/openapi.yaml
