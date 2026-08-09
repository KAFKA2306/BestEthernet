# VR会場ネットワーク事前診断

BestEthernetの既存測定ログから、会場ごとの候補回線を同一条件で比較するための技術MVPです。

## 無料sample

`examples/network-readiness-output/network-readiness.html` は合成データから生成した公開用sampleです。IPアドレスは公開モードでマスクされます。

```powershell
python network_readiness.py `
  --job examples/network-readiness-job.json `
  --samples examples/network-readiness-measurements.jsonl `
  --output-dir examples/network-readiness-output `
  --public
```

実測時は同じjob IDを測定ログへ付与します。

```powershell
python speed_test_and_select.py --job-id venue-YYYYMMDD-001
```

各候補は最低3回以上測定し、reportではlatency/download/uploadの中央値、download/uploadの最小値を表示します。requested interfaceとactual interfaceが一致しないsample、失敗sample、job IDが一致しないsampleは正常データとして採用しません。

## 判定の意味

`MEETS_CONFIGURED_THRESHOLDS` はjob manifestに設定したスクリーニング閾値を満たしたことだけを意味します。VRChat、HMD、会場Wi-Fi、イベント成功、SLAを保証しません。十分な有効sampleがない場合は`INSUFFICIENT_EVIDENCE`とし、primary/fallbackを捏造しません。

## Windows / 権限

現行のライブ測定・アダプター分離はWindows PowerShellの`Get-NetAdapter`等を利用します。アダプターの有効化・無効化を行う運用では管理者権限が必要になる場合があるため、開催前にdry-runと復元確認を実施してください。WindowsのモバイルホットスポットはWi-Fi、Ethernet、携帯データ回線の共有に利用できますが、BestEthernetの測定結果だけでその品質を保証しません。

## 有償PoCの範囲

無料sampleはreport形式・集計方法・fail-closed挙動の確認用です。有償PoC候補は、実会場または顧客想定環境での複数回測定、primary/fallback構成案、当日runbook、測定証跡の納品です。通信品質やイベント成功の保証は含めません。

## CTA

- [サンプル診断を見る](../../examples/network-readiness-output/network-readiness.html)
- [会場の事前診断を相談する](https://github.com/KAFKA2306/BestEthernet/issues/new)
- [次回イベントの回線構成を相談する](https://github.com/KAFKA2306/BestEthernet/issues/new)

## プライバシーを保つ検証台帳

営業・検証の集計では個人情報、source IP、gatewayを保存せず、次の状態だけを件数で記録します。

| event | count |
|---|---:|
| sample_report_opened | 0 |
| diagnostic_guide_opened | 0 |
| venue_inquiry_started | 0 |
| qualified_inquiry | 0 |
| diagnostic_demo_completed | 0 |
| paid_pilot | 0 |

公開後60日の目標値はIssue #3を正準とし、実測値が得られたときだけ更新します。未実施の提案・デモ・有償PoCを実績として記録しません。
