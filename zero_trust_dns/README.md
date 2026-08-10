# Zero-Trust DNS PoC

第三者DNSを無条件に信用せず、**DNS resolver 自体も侵害され得る**前提で、広告・トラッカー遮断用DNSを private / fail-closed に運用するための実証です。

## 現在の到達点

このディレクトリは production DNS server そのものではありません。GitHub Actions で次を毎回検証する、再現可能な安全性PoCです。

- AdGuard HomeのversionとLinux amd64配布物SHA-256を固定する
- public DNS listenerを禁止する
- public admin UIを禁止する
- 接続元をloopbackまたはTailscaleの`100.64.0.0/10`に限定する
- upstream DNSを暗号化DoT/DoHに限定する
- Quad9 Secureをupstream候補として固定する
- EDNS Client Subnetを禁止する
- DNSSEC DOを有効にする
- query logは監査用に有効化するがGitへcommitしない
- 危険なpolicyへ改変したnegative fixtureが必ず失敗することをself-testする
- 公式AdGuard Home binaryをloopbackだけで起動し、install APIでもloopback-only bindを検証する

## Trust boundary

```text
Android / PC
    |
    | authenticated private network (Tailscale)
    v
AdGuard Home
    |  policy / filtering / local audit
    |  encrypted DNS only
    v
Quad9 Secure
    |  threat blocking + DNSSEC validation upstream
    v
Internet
```

AdGuard HomeをInternetへ公開する設計ではありません。Android標準Private DNSへpublic DoT endpointを公開する構成も、このPoCのproduction targetにはしません。

## Policy contract

`policy.json`がmachine-readableな正準です。`verify_policy.py`は安全条件をfail-closedで検証します。

```bash
python3 zero_trust_dns/verify_policy.py
```

`0.0.0.0/0`、plaintext upstream、public admin、query logのGit保存などへ変更するとCIは失敗します。

## CI evidence

`.github/workflows/zero-trust-dns-poc.yml`は以下を実行します。

1. GitHub公式`actions/checkout`をcommit SHAで固定してcheckout
2. policyとnegative testを検証
3. AdGuard Home公式release archiveをHTTPSで取得
4. pinned SHA-256とbyte-for-byte照合
5. 公式binaryのversionを確認
6. installerを`127.0.0.1:3000`だけで起動
7. 公式install APIの`check_config`でweb=`127.0.0.1:3001`、DNS=`127.0.0.1:5353`を検証
8. wildcard bindが無いことを検査

## Androidについて

このPoCはAndroid端末へ設定を書き込むものではありません。production化では、AndroidをTailscaleのidentity境界へ参加させ、tailnet内のprivate DNSとしてAdGuard Homeへ到達させます。端末実機での接続、広告遮断、Google/Audible等の回帰、captive portal復旧は別のacceptance gateとして実測してからproduction扱いにします。

## 一次情報

- AdGuard Home Configuration: https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration
- AdGuard Home Technical Documentation / install API: https://github.com/AdguardTeam/AdGuardHome/blob/master/AGHTechDoc.md
- AdGuard Home releases: https://github.com/AdguardTeam/AdGuardHome/releases
- Tailscale DNS: https://tailscale.com/kb/1054/dns
- Quad9 services: https://docs.quad9.net/services/
- DNSSEC architecture: https://www.rfc-editor.org/rfc/rfc4033

## 非達成

現時点では以下を「実績済み」とは主張しません。

- Android実機がこのDNSを常用している
- 広告を100%遮断できる
- malwareを100%遮断できる
- resolver侵害を完全に防げる
- production serverへ自動deploy済み

これらは証拠が取得できた時点でのみ更新します。
