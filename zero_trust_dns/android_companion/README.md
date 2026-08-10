# ZeroTrustDNS Android Companion

Android側の目的は、VPNを自作することではなく、**公式Tailscaleを通信境界として使い、ZeroTrustDNSが実際に適用されたことだけを1ボタンで確認する**ことです。

## ユーザー操作

APKを開いて表示されるボタンは1つです。状態に応じて自動的に次の操作へ進みます。

1. Tailscale未導入 → 公式Google Play / Tailscale配布ページを開く
2. Tailscale導入済み・VPN未接続 → Tailscaleを開く
3. VPN接続済み → `ready.zerotrustdns.test` をAndroid標準resolverで自動解決
4. canaryがTailscale `100.64.0.0/10`へ解決 → **「保護は有効です」**
5. VPNは有効だがcanary不一致 → Tailscale DNS Adminへ進む

アプリへ戻るたびに状態を自動再検証します。

## なぜ自作VPNにしないか

Android `VpnService`はアプリが端末トラフィックを受け取れる強い権限境界です。Android公式仕様でも、最初の利用時には`VpnService.prepare()`によるユーザー同意が必要です。このcompanionは`VpnService`を宣言せず、VPN dataplaneはTailscale公式Android client (`com.tailscale.ipn`) に限定します。

## canary

Windows one-click installerがAdGuard Home公式rewrite APIを使って、次を生成します。

```text
ready.zerotrustdns.test -> <ZeroTrustDNS hostのTailscale IPv4>
```

Android companionは、単に「VPNアイコンが出ている」だけでは成功扱いにしません。Androidのsystem resolverでこのcanaryを引き、返答がTailscale CGNAT (`100.64.0.0/10`) に入ることまで確認します。

## APK CI/CD

`.github/workflows/zero-trust-dns-android.yml`で以下を実行します。

- Android Gradle Plugin 9.3.1
- Gradle 9.5.0
- JDK 17
- compile / target SDK 36 (Android 16)
- lint
- VPN / Accessibility / QUERY_ALL_PACKAGES / WRITE_SECURE_SETTINGS / overlay権限が増えていないことをfail-close検査
- `apksigner verify`
- APK SHA-256生成
- `ZeroTrustDNS-Android-preview.apk`をGitHub Actions artifactとして30日配布

## 現在の配布境界

CI artifactはAndroid SDKのdebug signingでインストール可能な**preview APK**です。恒久的な更新可能APKとして配るには、同一のrelease signing keyをGitHub Secret等の非公開領域に設定する必要があります。秘密鍵をrepoへcommitしてこの制約を回避することはしません。

## Android OS上、消せない確認

個人端末をDevice Owner / MDM管理下に置かない限り、次はOS/identity境界として残ります。

- Tailscale初回identity login
- AndroidによるVPN構成への同意

Android公式ではAlways-on VPNを無操作で設定できる`DevicePolicyManager.setAlwaysOnVpnPackage`はdevice/profile owner向けAPIです。一般アプリが勝手にこの確認を回避する設計にはしません。

## 一次情報

- Android 16 / API 36: https://developer.android.com/about/versions/16/behavior-changes-16
- Google Play target API requirement: https://developer.android.com/google/play/requirements/target-sdk
- Tailscale Android: https://tailscale.com/docs/install/android
- Tailscale Android MDM: https://tailscale.com/docs/integrations/mdm/android
- Tailscale DNS override: https://tailscale.com/docs/reference/dns-in-tailscale
- Android VPN: https://developer.android.com/develop/connectivity/vpn
- Android VpnService: https://developer.android.com/reference/android/net/VpnService
- Android DevicePolicyManager: https://developer.android.com/reference/android/app/admin/DevicePolicyManager
- AdGuard Home v0.107.78 OpenAPI: https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.78/openapi/openapi.yaml
