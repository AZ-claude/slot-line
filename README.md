# slot-line

`slot-line` は、LINE収集の実機PoCを進めるプロジェクトです。

現在はエムアンドエム溝口の`passive`を本番収集系として扱い、PIA町田（東京都）とPIA京急川崎（神奈川県）は別の手動regression targetとして保持しています。店舗masterと公式LINE source metadataの正はslot側です。slot-lineのnormalizedは`hall_id × line_source_key × date`で識別し、`collector_key`は内部RAW/Adapter用に限定します。設計の正は [`DESIGN.md`](DESIGN.md)、実機記録は [`PHASE0.md`](PHASE0.md) です。

## Status

🚧 Phase 1/運用準備 — `passive`と`text_trigger`を採用方式として固定。rich-card-only返信のRAW保存、production runner、regression runner、Task Scheduler経由のdry-runを確認済み。PIA regression targetの自動Scheduler登録は行っていません。

## Phase 1 runner

個別のPIA regressionをWindows運用機で手動確認する場合は、次の既存runnerを使えます。通常のregression取得には下記の専用runnerを使用し、標準のtrigger方式はAndroidのLINE URL schemeです。

```powershell
python scripts\run_pia_machida.py
```

本番収集系の手動runnerは次です。現在のproduction targetはM&Mのみで、PIA regression targetは含みません。

```powershell
python scripts\run_daily.py
```

Task Scheduler登録前の安全な実行環境確認は、次で行います。Adapterを起動せず、Python、ADB、Androidへのread-onlyコマンド、LINE package、RAWディレクトリ書き込みだけを確認します。PIA町田への送信とM&Mの取得は行いません。

```powershell
python scripts\run_daily.py --dry-run
```

summaryにはADB health、各collector keyのstatus、今回runの`message_count`、保存総数`stored_message_count_total`、`image_count`、errors/warnings、`raw_path`を出力します。

PIA町田とPIA京急川崎のregression targetは別runnerです。引数なしでは計画表示だけを行い、実機操作には明示的な`--execute`が必要です。Task Schedulerからは呼び出しません。

```powershell
python scripts\run_regression_targets.py
python scripts\run_regression_targets.py --execute
```

通常runの最終summaryは、同日複数回でも上書きせず、`data/logs/run_daily_YYYY-MM-DD.log`へ1実行1 JSON行で追記します。各Adapterの`run_id`、RAW path、前回trigger情報、`process_exit_code`も記録します。

PIA active triggerは`hall_id`・`line_source_key`・`latest_information` actionごとの10分cooldownで制御します。cooldown中は`skipped_cooldown`として操作をskipし、10分経過後は再実行可能です。現在日と前日manifestを確認して日付境界をまたぐcooldownも適用します。`--force-trigger`はありません。

Active collectorはtargetのsource keyと店舗タイトルを完全一致確認してから1回だけactionを実行し、実行前後のUI XMLとスクリーンショットをRAW保存します。外部Webへ移動した場合はURLとActivityも保存します。返信の新規行・rich card更新などの意味判定は後段へ委ね、`captured`はtarget確認・action実行・post-action capture・RAW保存の成功を示します。

旧方式のWindows UI Automation送信は、明示的に `--trigger-mode windows-uia` を指定した場合だけdebug/fallbackとして使用します。現在開いているWindowsトークへの盲目的送信は本番方式ではありません。

RAWは `data/raw/YYYY-MM-DD/<collector_key>/` に保存されます。既存adapterの`store_id`変数はcollector keyの後方互換名であり、canonical hall IDではありません。`manifest.json` は実行単位でupsertし、同一SHA-256の画像は再保存しません。実行時に作るTask Schedulerタスクは一時的な対話セッション用で、終了時に削除します。

保存形式は全店舗で次に固定します。

```text
data/raw/YYYY-MM-DD/<collector_key>/
  manifest.json
  messages.json
  images/
  ui/
```

通常配信型A「エムアンドエム溝口」はtriggerを送らず、既存受信メッセージをAndroid UI階層から取得します。

```powershell
python scripts\run_m_and_m_mizoguchi.py
```

画像はWindows側でSHA-256を確認してから保存し、同じSHA-256は既存ファイルを再利用します。Windowsへのpull、ハッシュ確認、manifest保存が完了した後だけAndroid一時画像を削除し、削除失敗は`cleanup_warning`として記録します。

通常のAndroid操作に人間フォールバックはありません。ADB接続、セキュアロック、LINEの構造取得、送信、返信待ち、画像保存、pullの失敗はマニフェストに状態を記録して終了します。

### Task Scheduler本番定義

- task名: `SlotLineDaily`（登録済み）
- 実行時刻: 毎日21:05（既存設定。現在の`run_daily.py`はM&Mのproduction adapterのみを実行し、PIA regression targetは対象外）
- command: `C:\Users\Eita Ideguchi\AppData\Local\Programs\Python\Python312\python.exe C:\Users\Public\slot-line\scripts\run_daily.py --repo-root C:\Users\Public\slot-line`
- working directory: `C:\Users\Public\slot-line`
- timeout: 15分
- 重複起動: `IgnoreNew`（前回実行中は新規起動しない）
- PCがスリープ中: 起床させず、その回は実行しない
- missed start: 自動追実行しない。次回定刻または明示的な手動実行で確認する
- ログ保存先: `C:\Users\Public\slot-line\data\logs\run_daily_YYYY-MM-DD.log`

登録直後の手動実行は行っていません。初回実行は次の21:05のscheduled runに任せます。

### Regression Task Scheduler定義

- task名: `SlotLineRegression`
- 実行時刻: 毎日21:16（21:15に既存の一回限りの`Schedule Work`があるため1分ずらして登録）
- command: `C:\Users\Eita Ideguchi\AppData\Local\Programs\Python\Python312\python.exe C:\Users\Public\slot-line\scripts\run_regression_targets.py --repo-root C:\Users\Public\slot-line --execute`
- timeout: 15分
- 重複起動: `IgnoreNew`
- `WakeToRun=false`, `StartWhenAvailable=false`
- PIA町田・PIA京急川崎を順番に実行。identity-scoped 10分cooldown中は再送しない
- 既存の`SlotLineDaily`は変更しない。登録後はdry-runだけ実施し、登録直後のtrigger手動実行は行わない

2026-09-21の実機確認では、ADB論理再接続、LINE強制終了後のADB起動、画面OFF後のADB復帰、物理USB再接続が成立しました。Windows再起動はユーザーによるWindows再起動後に復帰確認、Android本体再起動はキーガード解除後に復帰確認となり、完全無人復旧は未成立です。画面ロック方式やセキュリティ設定は変更していません。

## Repository

- Default branch: `main`
- Issueや設計、使い方は今後ここに整理します

## LINE日次観測

canonical RAWから店舗×日付の正規化JSONを生成するconverter、軽量validation、未収集日fixtureは [`docs/LINE_DAILY.md`](docs/LINE_DAILY.md) にまとめています。要約はRAWではなく派生値として扱い、今回のconverterはAI要約を実行しません。
