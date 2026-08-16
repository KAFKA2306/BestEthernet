# BestEthernet

旅先や会場で使える回線を固定的に決めず、**その場で候補を測定し、根拠を残して選び直す**ための Windows 向けツール群です。

## Vision

ホテル Wi-Fi、スマートフォン回線、有線 LAN など複数の経路が使える環境で、ブランド名や過去の平均値ではなく、現在の測定結果から接続先を判断できるようにします。

## Design philosophy

- 回線種別ではなく実測値で比較する。
- latency、download、upload を別々に記録する。
- requested interface と actual interface が一致しない測定を正常値として扱わない。
- 測定前のアダプター状態を復元する。
- 過去の測定値を現在の品質保証として使わない。
- HMD と PC のローカル無線品質と、PC からインターネットへの uplink 品質を混同しない。
- 閾値は利用者が定める判定条件であり、VR、VRChat、HMD、会場 Wi-Fi、イベント品質の保証とは扱わない。

## Why

Windows の設定画面を行き来しながら勘で回線を選ぶ代わりに、候補インターフェースを同じ方法で測定し、測定経路・結果・失敗理由を保存できます。複数回の測定がある場合は、既存の `network_readiness.py` で候補ごとの集計と primary / fallback 候補を生成できます。

## 現在実装されていること

### 回線測定

`speed_test_and_select.py` は Windows の `Get-NetAdapter`、`Get-NetIPConfiguration`、`Get-NetRoute` を使って接続中の物理アダプターを列挙し、loopback、VPN、Hyper-V、WSL、Bluetooth、TAP、TUN、WireGuard などを既定で除外します。

`speedtest-cli` は対象アダプターの IPv4 source address に bind して実行され、以下を `SpeedSample` として記録します。

- requested interface
- actual interface
- source IP
- gateway
- measurement server
- timestamp
- latency
- download Mbps
- upload Mbps
- success / failure reason
- optional job ID

測定時に候補アダプターを分離した場合も、処理後は元の administrative state へ復元します。route は監査用に読み取りますが、このスクリプトは route を変更しません。

```powershell
python speed_test_and_select.py --dry-run
python speed_test_and_select.py
```

live measurement には `speedtest-cli` が必要です。

### 複数回測定の集計

`network_readiness.py` は既存の JSONL 測定ログを読み込み、候補ごとに次を計算します。

- sample count / successful sample count
- latency median
- download median / minimum
- upload median / minimum
- configured thresholds を満たしたか
- rejected sample の理由
- primary / fallback candidate

必要サンプル数は 3 以上です。requested interface と actual interface が一致しない測定、失敗した測定、数値が不正な測定は集計対象から除外されます。公開レポートでは source IP / gateway をマスクできます。

判定結果は、設定された閾値に対する比較です。VR が利用可能であることを自動的に証明するものではありません。

### Windows Mobile Hotspot

この repository には `hotspot_activator.py` と `hotspot_interface_selector.py` があります。Windows 自体も Wi-Fi、Ethernet、cellular data connection を Mobile Hotspot で他端末へ共有できます。

Microsoft の現行手順:
https://support.microsoft.com/windows/use-your-windows-device-as-a-mobile-hotspot-c89b0fad-72d5-41e8-f7ea-406ad9036b85

### 手動操作

- `ethernet_switcher_gui.py` — interface の手動切替
- `enable_all_interfaces.py` — network interface の有効化
- `hotspot_activator.py` — Mobile Hotspot 操作
- `hotspot_interface_selector.py` — Hotspot の共有元 interface 選択

一部の Windows network 操作には管理者権限が必要です。

## VRChat のネットワーク要件との関係

この repository の旧 README では「最低 100 Mbps、推奨 150 Mbps」を一般的な VR 要件として記載していましたが、現在の VRChat 公式 System Requirements は network について **Broadband Internet Connection (25+ megabit preferred)** としています。そのため 100 / 150 Mbps を VRChat の一般要件としては扱いません。

VRChat 公式 System Requirements:
https://help.vrchat.com/hc/en-us/articles/1500002378722-System-Requirements

また、internet uplink の speed test は PC↔HMD 間の Wi-Fi 品質を直接測定しません。無線 PCVR を評価するときは、この2つを別の経路として確認してください。

## 過去の測定データ

repository には 2024 年 3 月 2 日から 2024 年 10 月 22 日までの測定記録があります。これらは**過去の観測例**であり、現在の hotel Wi-Fi、Vodafone、O2 等の性能保証ではありません。

過去の集計:
- [`results.md`](results.md)
- [`examples.md`](examples.md)

同じ回線でも測定時刻や場所によって結果が変わるため、利用時点で再測定してください。

## 基本的な利用順序

1. `python speed_test_and_select.py --dry-run` で候補を確認する。
2. live measurement を実行して JSONL / CSV へ結果を残す。
3. 必要なら同じ `job_id` で各候補を複数回測る。
4. `network_readiness.py` で複数回測定を集計する。
5. 測定結果と実際の用途を見て回線を選ぶ。
6. 必要なら Windows Mobile Hotspot で接続を共有する。
7. 状況が変わったら再測定する。

## 検証

GitHub Actions の `Test network safety` で、測定ロジック、interface safety、状態復元、network readiness 集計を検証しています。

Repository:
https://github.com/KAFKA2306/BestEthernet

## 制約

- 主要な network 操作は Windows 向けです。
- live speed test は外部の測定 server とネットワーク状態に依存します。
- 測定値は将来の品質を保証しません。
- `network_readiness.py` の閾値は利用者設定であり、製品・サービス公式の性能要件ではありません。
- repository の測定は internet uplink を中心に扱い、PC↔HMD のローカル無線リンクそのものを測定するものではありません。
