# LINE日次観測

## 責務境界と保存単位

`slot` が canonical hall master、`hall_id`、公式LINE source metadataを所有する。`slot-line` はLINE取得、RAW保存、日次normalized observation、trigger/Android処理だけを担当する。slot-lineに店舗masterや店舗名によるruntime補完を持ち込まない。

normalized observationの識別単位は次の複合キーである。

```text
hall_id × line_source_key × date
```

保存先とファイル名は次の形式とする。`line_source_key`の`@`などはファイル名ではURL percent-encodingされる。

```text
data/normalized/line_daily/YYYY-MM-DD/<hall_id>__<quoted-line_source_key>.json
```

`collector_key`はRAWディレクトリとAdapter選択用のslot-line内部キーで、canonical join keyではない。旧RAWの`store_id`もcollector keyとしてのみ扱う。normalized JSONに`store_id`は持たせない。

## schema v2

必須identityは次の通り。

```json
{
  "schema_version": 2,
  "hall_id": "abiba-kami-oka-ten",
  "collector_key": "abiba-kami-oka-ten",
  "line_source_key": "@bzi0364s",
  "date": "2026-09-23",
  "source": "official_line"
}
```

`hall_id`はslotのcanonical IDを明示的に受け取る。RAWにそれがなく、外部source metadataからも渡されない場合はnormalizedを生成せずfail closedする。店舗名、collector key、LINE表示名からのfuzzy matchingは行わない。

`line_source_key`は公式LINE sourceを識別するキーで、`hall_id`の代替ではない。同一hallに複数sourceがある場合はsourceごとに別JSONを保存し、一次normalizedでmergeしない。hall-day表示へのaggregationはslot側の別責務とする。

RAWとnormalizedの境界は以下の通り。

- RAW: original text、image、UI XML、rendered screenshot、manifest、messages。
- normalized: identity、date、acquisition/collection status、`line_update`、trigger結果、message件数/種別/時刻、summary、RAW refs。
- `summary`はRAWではなく再生成可能な派生データであり、このconverterはAI要約を実行しない。

## 状態の意味

- `line_update`: `present`は配信またはtrigger返信を確認、`absent`は正常確認済みで対象更新なし、`unknown`は未確認・timeout・取得失敗。
- `response_timeout`は`absent`に変換しない。
- `collection.status`: `success` / `partial` / `failed` / `not_checked`。
- `not_checked`のfixtureは`line_update=unknown`とし、配信内容を作らない。
- 同一sourceの複数runは、`success`または`skipped_already_successful`を優先する。timeoutや`skipped_already_attempted`を成功・absentへ丸めない。

`raw_refs.run_ids`にはRAWが持つ実run IDだけを記録する。旧manifestのようにrun IDが存在しない場合は推測せず空配列とし、`raw_refs.record_refs`（例:`manifest.json#0`）でmanifestレコード位置を追跡する。

## RAWからの再生成

RAW manifestに`hall_id`と`line_source_key`がある場合はそれを使う。旧RAWにidentityがない場合だけ、slot側のsource metadataから明示的に渡す。

```bash
python3 scripts/line_daily.py convert \
  data/raw/2026-09-21/pia_machida \
  --repo-root . \
  --hall-id <slotのcanonical-hall-id> \
  --line-source-key @030pwlwx \
  --store-master /path/to/slot/src/features/hall-registry/halls.csv
```

同一RAW directory内に複数sourceがある場合は`convert`がsource別ファイルを生成する。Python APIでは`convert_raw_directory_all()`を使う。`convert_raw_directory()`は単一sourceの場合だけ成功し、複数sourceを1件へmergeしない。

RAW本体は読み取り専用で、converterはmanifest/messages/images/uiを書き換えない。PIA町田の現存旧RAWはrich cardとimageを含む成功記録を検出できるが、現ローカルで確認できるslot hall/source metadataにPIA町田のcanonical bindingがないため、identity引数なしではnormalizedを生成しない。`@030pwlwx`はsource ID候補として利用できるが、hall_idを推測する根拠にはならない。

## 未収集fixture

```bash
python3 scripts/line_daily.py not-checked \
  --repo-root . --date 2026-09-23 \
  --hall-id abiba-kami-oka-ten \
  --line-source-key @bzi0364s \
  --line-source-key @isg5065c \
  --line-source-key @072akruj \
  --store-master /path/to/slot/src/features/hall-registry/halls.csv
```

10店舗のfixtureはslot側で確認されたcanonical hall IDを使い、`not_checked` / `unknown`を維持している。複数sourceの店舗はsourceごとにファイルを分けている。

| hall_id | source fixture | source数 |
| --- | --- | ---: |
| `123-yokohama-nishiguchi-ten` | `@rvs1554c`, `@123yokohama` | 2 |
| `abiba-ebina-ten` | `@743tmazu`, `@aviva5555` | 2 |
| `abiba-kami-oka-ten` | `@bzi0364s`, `@isg5065c`, `@072akruj` | 3 |
| `abiba-miharu-machi-ten` | `@aviva0422miharu`, `@gga9118w`, `@441scmdp` | 3 |
| `abiba-minamiashigara-ten` | `@edr3119j`, `@039ujzic` | 2 |
| `abiba-sekiuchi-ten` | `YRBeiYiST8` | 1 |
| `abiba-sh-nandai-ten` | `@lxh1446l` | 1 |
| `abiba-shinsugita-ten` | `@521hisef` | 1 |
| `abiba-tsunashima-minami-ten` | `@585sgrtl`, `@120gvvvr` | 2 |
| `abiba-tsunashima-taru-machi-ten` | `@vbv7336k` | 1 |

M&M溝口のcanonical RAWはMac checkoutにないため、実データfixtureを捏造していない。Windows/Android実機から正本RAWとslot側source metadataが揃った時点で同じconverterを実行する。
