# slot-line

`slot-line` は、LINE収集の実機PoCを進めるプロジェクトです。

現在はPIA町田1店舗に限定したPhase 1最小E2Eを固定しています。設計の正は [`DESIGN.md`](DESIGN.md)、実機記録は [`PHASE0.md`](PHASE0.md) です。

## Status

🚧 Phase 1 PoC — PIA町田 `text_trigger` E2Eを実機確認済み。

## Phase 1 runner

Windows運用機で、リポジトリルートから次を1回実行します。標準のtrigger方式はAndroidのLINE URL schemeで、通常運用にWindows版LINEの起動や現在の表示トークは要求しません。

```powershell
python scripts\run_pia_machida.py
```

処理は、WindowsからADBで `https://line.me/R/oaMessage/%40030pwlwx/?%E6%9C%80%E6%96%B0%E6%83%85%E5%A0%B1` をAndroidへ開き、UI階層で `PIA町田` と入力欄の `最新情報` を完全一致確認してから送信します。対象確認できない場合は送信せず終了します。返信は `uiautomator` で検知し、LINE標準のダウンロード操作、`adb pull`、SHA-256/byte size記録までを行います。

旧方式のWindows UI Automation送信は、明示的に `--trigger-mode windows-uia` を指定した場合だけdebug/fallbackとして使用します。現在開いているWindowsトークへの盲目的送信は本番方式ではありません。

RAWは `data/raw/YYYY-MM-DD/pia_machida/` に保存されます。`manifest.json` は成功・失敗を実行単位で追記し、同一SHA-256の画像は再保存しません。実行時に作るTask Schedulerタスクは一時的な対話セッション用で、終了時に削除します。

通常のAndroid操作に人間フォールバックはありません。ADB接続、セキュアロック、LINEの構造取得、送信、返信待ち、画像保存、pullの失敗はマニフェストに状態を記録して終了します。

2026-09-21の実機確認では、ADB論理再接続、LINE強制終了後のADB起動、画面OFF後のADB復帰とLINE再起動が成立しました。Android本体再起動後のセキュアロック解除要否、物理USB再接続、RSA永続性は未確認です。画面ロック方式やセキュリティ設定は変更していません。

## Repository

- Default branch: `main`
- Issueや設計、使い方は今後ここに整理します
