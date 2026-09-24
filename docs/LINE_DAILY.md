# LINE日次観測

## 保存場所

正規化データは canonical RAW と分離して保存する。

```text
data/normalized/line_daily/YYYY-MM-DD/<store_id>.json
```

JSON Schemaの正本は [`schemas/line_daily.schema.json`](../schemas/line_daily.schema.json) で、実装上の軽量な意味検証は [`scripts/line_daily.py`](../scripts/line_daily.py) の `validate_observation` が行う。

`store_id` は既存店舗マスタのIDをそのまま参照する。公式LINE sourceの10件は `slot` リポジトリの `src/features/hall-registry/line-sources.csv` に、同じmasterの `hall_id` を外部キーとして保持する。現行のPoC RAWは過去のAdapter ID（`pia_machida`、`m_and_m_mizoguchi`）を使っているため、移行時に同一店舗のcanonical master IDとの対応を確定するまでは、converterへ既知ID集合を明示して検証する。店舗名だけでの補完はしない。

## 状態の意味

- `line_update`: `present` は配信またはtrigger返信を確認、`absent` は正常確認済みで対象日の新規メッセージなし、`unknown` は取得失敗・timeout・未確認。
- `collection.status`: `success` / `partial` / `failed` / `not_checked`。
- `collection.failure_code`: RAW manifestの低レベルコードを保持する。`response_timeout` は `absent` へ変換しない。
- `summary`: RAWではなく派生値。`pending` / `generated` / `not_applicable` / `failed` を持つ。今回のconverterはAI要約を実行せず、更新ありは `pending` とする。
- `acquisition_type=unknown`: 未収集店舗のAdapter分類を捏造しないための値。10店舗の未収集fixtureはこの値を使う。

同一日複数runでは、`success`（または既存成功を示す `skipped_already_successful`）を優先する。timeoutや `skipped_already_attempted` を先に見て `absent` や成功へ丸めない。全runはRAW manifestに残り、run IDを持つ新schemaのRAWは `raw_refs.run_ids` から追跡できる。旧manifestにrun IDがない場合は空配列を維持し、IDを推測しない。

## RAWからの再生成

```bash
python3 scripts/line_daily.py convert \
  data/raw/2026-09-21/pia_machida \
  --repo-root . \
  --output data/normalized/line_daily/2026-09-21/pia_machida.json
```

`messages.json` が存在する場合はそれを使用し、旧RAWのように存在しない場合だけ manifest の `message_types` / `message_times` を読み取り専用で補完する。RAW本体は書き換えない。

未収集日の生成例:

```bash
python3 scripts/line_daily.py not-checked \
  --repo-root . --date 2026-09-23 \
  --store-id <existing-store-id> \
  --store-master /path/to/slot/src/features/hall-registry/halls.csv
```

## 既存サンプル

- [`data/normalized/line_daily/2026-09-21/pia_machida.json`](../data/normalized/line_daily/2026-09-21/pia_machida.json): 現存PIA RAWから生成。
- `data/normalized/line_daily/2026-09-23/`: 公式LINE確認済みで既存masterへ一意に対応できた10店舗の `not_checked` fixture。送信・友だち追加・実収集はしていない。
- M&M溝口の2026-09-23 canonical RAW本体はMac側checkoutに存在しないため、実データfixtureを捏造していない。Windowsからread-onlyでRAWを取得できた時点で同じconverterを実行する。

選定対象は一覧の公式LINE確認済み行から、現行masterへ住所・P-WORLD detail URLで一意に照合でき、PoC 2店舗を除外した候補を `hall_id` 昇順に並べた先頭10件とした。

```text
123-yokohama-nishiguchi-ten
abiba-ebina-ten
abiba-kami-oka-ten
abiba-miharu-machi-ten
abiba-minamiashigara-ten
abiba-sekiuchi-ten
abiba-sh-nandai-ten
abiba-shinsugita-ten
abiba-tsunashima-minami-ten
abiba-tsunashima-taru-machi-ten
```
