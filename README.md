# slot-line

`slot-line` は、LINE収集の実機PoCを進めるプロジェクトです。

現在はPIA町田1店舗に限定したPhase 1最小E2Eを固定しています。設計の正は [`DESIGN.md`](DESIGN.md)、実機記録は [`PHASE0.md`](PHASE0.md) です。

## Status

🚧 Phase 1 PoC — PIA町田 `text_trigger` E2Eを実機確認済み。

## Phase 1 runner

Windows運用機の対話セッションでLINEデスクトップ版のPIA町田トークを表示した状態で、リポジトリルートから次を1回実行します。

```powershell
python scripts\run_pia_machida.py
```

処理は、Windows UI Automationで `最新情報` をUnicode設定して送信し、AndroidをADBで起動・対象トークへ移動し、`uiautomator` でリッチカードと画像返信を検知します。その後、LINE標準のダウンロード操作、`adb pull`、SHA-256/byte size記録までを行います。

RAWは `data/raw/YYYY-MM-DD/pia_machida/` に保存されます。`manifest.json` は成功・失敗を実行単位で追記し、同一SHA-256の画像は再保存しません。実行時に作るTask Schedulerタスクは一時的な対話セッション用で、終了時に削除します。

通常のAndroid操作に人間フォールバックはありません。ADB接続、セキュアロック、LINEの構造取得、送信、返信待ち、画像保存、pullの失敗はマニフェストに状態を記録して終了します。

## Repository

- Default branch: `main`
- Issueや設計、使い方は今後ここに整理します
