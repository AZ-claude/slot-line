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
- active collectorが`semantic_interpretation=deferred`を記録した場合、画面RAW保存が成功していても返信内容は未解釈のため、messageが空なら`line_update=unknown`とする。
- `response_timeout`は`absent`に変換しない。
- `collection.status`: `success` / `partial` / `failed` / `not_checked`。
- `not_checked`のfixtureは`line_update=unknown`とし、配信内容を作らない。
- 同一sourceの複数runは、`success`または`skipped_already_successful`を優先する。timeoutや`skipped_already_attempted`を成功・absentへ丸めない。
- `summary.status`は、`present`だけを`pending`（要約対象RAWあり）とし、`absent` / `unknown`は`not_applicable`とする。

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

同一RAW directory内に複数sourceがある場合は`convert`がsource別ファイルを生成する。messageは`line_source_key`、manifest index、または`run_id`で1つのsource groupへ帰属できる必要があり、未帰属・曖昧・矛盾するmessageはfail closedする。Python APIでは`convert_raw_directory_all()`を使う。`convert_raw_directory()`は単一sourceの場合だけ成功し、複数sourceを1件へmergeしない。

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

## 店舗別collection policy

正本は`data/surveys/collection_policy_41_2026-09-26.json`で、`data/surveys/collection_policy_41_2026-09-26_review.json`（目視レビューと1回限りのaction mapping）とinventoryから生成する。

```
python3 -m scripts.active_acquisition_policy \
  --inventory data/surveys/active_acquisition_inventory_41_2026-09-26.json \
  --review data/surveys/collection_policy_41_2026-09-26_review.json \
  --output data/surveys/collection_policy_41_2026-09-26.json
```

| collection_type | 日次運用 |
| --- | --- |
| Type A `type_a_passive` | passive scanのみ |
| Type B `type_b_passive_plus_active` | passive scan + 定期active trigger。`text_trigger_verified=true`ならtext trigger、それ以外はverified rich-menu action |
| Type C `type_c_passive_external_web` | passive scanのみ。`external_url`は補助source |
| `unresolved` | passive scanのみ。証拠が揃うまで分類しない |

- rich menu labelはAccessibilityに出ないため、スクリーンショットの目視で読む。端末が横向きだとrich menuが表示されないので、縦向きで撮影する。
- Type Aは`absent_confirmed`か、収集用active actionがないことを実観測した店舗だけ。menuを読んで最新情報系ラベルがなくても`menu_reviewed_no_latest_label`の`unresolved`に留める。
- action mappingは明確な最新情報系タイルに1店舗1回だけ実行し、結果を見た場合のみ`line_reply`/`external_web`とする。LIFF同意画面は許可せず`liff_consent_required`として残す。
- rich menu tapで送信文字列が見えない（postback型）店舗は、text triggerの同等性を検証しない。
- ownerが手動で確認した結果（LIFF同意後の遷移先、ラベル内容の判断）は`owner_reported_action_result`/`owner_confirmed_no_collection_action`としてcollector観測と区別し、confidenceは`medium`に留める。

## 対象店舗の拡大（onboarding）

作業手順の詳細（禁止事項・画像レビュー・review記入・引き継ぎ）は [LINE_ONBOARDING_MANUAL.md](LINE_ONBOARDING_MANUAL.md) を参照。

候補は`slot-kanagawa-hall-master`の`halls.csv`とP-WORLD LINE一覧を店名で結合して作る（`data/surveys/line_target_candidates_kanagawa_2026-09-26.json`）。

```
python3 scripts/onboard_line_targets.py onboard --candidates data/surveys/line_target_candidates_kanagawa_2026-09-26.json \
  --hall-ids <30件以内> --output data/surveys/line_onboarding_batchNN_<date>.json --evidence-dir data/surveys/line_onboarding_batchNN_<date>_evidence
python3 scripts/onboard_line_targets.py registry   # data/line_targets.json を再生成
python3 scripts/collect_passive_incremental.py --target-set registry --run-id <id>
```

- 本人確認はプロフィールに出るP-WORLD URLがhall masterと一致するか、正規化した店名（末尾の「店」の有無は同一扱い）が一致した場合のみ。確認できなければ友だち追加しない。
- `lin.ee`短縮URLはMac側でリダイレクト先に解決してから開く。「表示できません」ダイアログのIDは無効として記録する。
- 端末は縦向き・画面点灯が前提（onboardは消灯時にWAKEUPし、横向きなら中断する）。
- registryモードは`data/line_targets.json`を読み、checkpointにない店舗は初回観測として基準化する。20/41の固定モードは変更しない。

## Windows PC版LINEでの日次取得（line_pc_collect）

Android より軽い Windows の PC版LINE で、登録店舗（`data/line_targets.json`）のトークを毎日取得する。PC版LINEは UI Automation に文字を出さないため、ウィンドウの撮影と Windows 標準の日本語OCRで読む。LINEのローカルデータファイルは読まない。

| ファイル | 役割 |
| --- | --- |
| `scripts/build_line_collection_plan.py` | policy表から `data/line_collection_plan.json` を作る（店舗ごとの検索名・分類・文字送信の要否） |
| `scripts/line_pc.py` | PC版LINEの操作部品（ウィンドウ固定、クリック、貼り付け、キー、撮影、OCR）。Windows上で動く |
| `scripts/line_pc_collect.py` | 日次取得の本体。Windows上で動く |
| `scripts/run_line_pc_collect.cmd` | タスクスケジューラから呼ぶ起動用バッチ（ログイン中のセッションで実行） |

1店舗ごとの流れ：

1. チャット検索に店名を貼り付けて先頭の結果を開き、ヘッダーをOCRで照合する（類似度0.6未満なら何もしない・何も保存しない）
2. `--send` のときだけ、`text_trigger=daily` の店舗に「最新情報」を送る（1日1回）。`--verify` を付けると `verify_once` の店舗に**生涯1回だけ**送り、返信の有無を記録する
3. トークの一番下から上へ撮影し、前回の最後の行（`data/line_pc_state.json`）に届くか、最上部か、`--max-pages` で止める
4. `data/raw/<日付>/<hall_id>/line_pc/<run>_pNN.jpg`（画面の切り抜き）と `…_pNN.json`（OCR行）を保存し、`data/raw/<日付>/line_pc_run_<run>.json` に結果をまとめる

### LLM なしで回すための仕組み

日次取得は LLM を使わない（Python・pywin32・Windows 標準OCRのみ）。人やAIの判断が要らないよう、次を自動で行う。

- **返信の自動判定：** 送信の前後でトーク最下部を撮り、自分の緑の吹き出し（RGB 195,246,157）より下の左端に店舗の投稿（画像・アイコン・吹き出し）があれば返信ありとする。吹き出しが見えず画面が変わっていれば、返信で押し上げられたとみなす。画面が変わらなければ送信未確認。
- **確認送信の自動切替：** `verify_once` の店舗は1回だけ送り、結果を Windows の `data/line_pc_state.json` と `data/line_text_trigger_results.json` に書く。次回から「返信あり」は毎日送信、「返信なし」は送信しない（プランを作り直さなくても切り替わる）。
- **失敗の通知：** 取得できなかった店舗を毎回 `data/line_pc_alerts.log` に1行で追記し、3店舗以上失敗した日は Windows のトースト通知を出す。manifest の `summary.failed` にも理由つきで残る。
- **OCR の読み違いへの対応：** 店名照合で外れる店舗は、コードを直さず `data/line_ocr_aliases.json` の `stores` に `"<hall_id>": ["OCRでの読み"]` を足す（例：`"nakayama-uno": ["中山LJN0"]`）。

文字送信の確認結果は `data/line_text_trigger_results.json`（`{"stores": {"<hall_id>": {"result": "reply" | "no_reply"}}}`）に書き、`build_line_collection_plan.py` を再実行すると `daily` / `off` に切り替わる。

- 実行中はPC版LINEのウィンドウを操作するので、PCを触らない・画面をロックしない。
- RAW（画面の切り抜きとマニフェスト）は Windows の `D:\slot-line\raw\<日付>\` に保存する（`run_line_pc_collect.cmd` の `--raw-root`。C: の空きが少ないため 2026-10-02 に移した）。Mac 側の `line_pc_sync.py` もここから取る。
- RAWには画面の切り抜きが入る。店舗のトーク以外は保存しない作りだが、RAWはWindows側だけに置き、公開リポジトリにcommitしない。
- 横スクロールのカルーセル（左右どちらかの端で切れたカード行）は、「<」で先頭まで戻してから「>」を押して1枚ずつ `…_pNN_cK_MM.jpg` に保存し、「もっと見る」か変化なしで止める。押した結果別ウィンドウが開いたらEscで閉じて止める。
  - 行の上下は端の列だけでなく実際の余白から求める（カードの端が白っぽいと検出がずれ、帯とクリック位置が外れるため）。高さ約338pxに満たない行はページ端で切れているので、次のページで撮る。
  - 矢印はマウスを動かして重ねたときだけ反応するので、横から動かしてから押す。押しても動かず、右端のカードがまだ切れていれば最大3回まで押し直す。それでも動かなければ `stuck_before_last_card` と記録し、マニフェストの `summary.incomplete_carousels` に載せる（Mac側はそのカードを使わない）。

- 店舗のトークは検索欄に名前を貼り付けて開く。検索結果では一致部分が緑色になり、Windows OCR は緑の小さな文字を読み違えるので、検索結果と見出しは「各画素で最も暗い色」に変換して2倍に拡大してから読む。濁点・半濁点（ぶ/ぷ）と長音（ー/-）の違いは無視し、一致した行そのものをクリックする。チェーンの別店（「くいーぷ東戸塚店」と「くいーぷ」）は一致とみなさない。
- 開けなかった店舗はマニフェストの `open.result_ocr` / `header_ocr` に読めた文字（画像は残さない）を記録する。直すときは `data/line_ocr_aliases.json` に名前を足す。

### スケジュール（Windows タスク `SlotLineLinePc`）

- 毎日 21:30、ログイン中のセッションで `scripts\run_line_pc_collect.cmd --send --plan <plan>` を実行する。
- 2026-10-02 から全店舗（`data/line_collection_plan.json`、`--send --verify`）で実行している。2026-10-01 は精度確認のため7店舗（`data/line_collection_plan_test.json`）に絞っていた。
- 毎日の撮影は前回の続きだけを撮る。前回の最下部の文字（`checkpoint_lines`）が見つかるか、前回の撮影日より古い日付の区切り（「9.30(水)」など、白い背景の上の中央の小さな文字）が見えたところで止まる。画像しか送らない店舗も、日付の区切りで止まる。1店舗あたり約20〜30秒。
- まだ1通もメッセージがない店舗はPC版LINEの検索に出ない（グランドホール長後、2026-10-02）。`no_messages_yet` と記録し、失敗には数えない。
- 旧タスク `SlotLineDaily`（21:05、Android の M&M 単独取得）と `SlotLineRegression`（21:25、Android の回帰テスト）は owner の指示で 2026-09-30 に削除した。

## Mac側：投稿ごとの切り分けと重複除去（LLMなし）

Windows の取得結果を Mac に取り込み、投稿1件ずつの画像にする。LLMは使わない。画面の切り抜き（個人情報を含みうる）なので、`data/line_pc_raw/` と `data/line_pc_posts/` は git 対象外。

```
python3 scripts/line_pc_sync.py                 # Windows → data/line_pc_raw/<date>/（直近3日）
.venv/bin/python scripts/line_pc_posts.py       # → data/line_pc_posts/
```

`.venv` は `python3 -m venv .venv && .venv/bin/pip install pillow numpy` で作る（Pillow と numpy が必要）。

出力：

| パス | 中身 |
| --- | --- |
| `data/line_pc_posts/<hall_id>/<post_id>.jpg` | 投稿1件の画像（複数枚を1度に送った投稿は縦に並んだまま1件） |
| `data/line_pc_posts/<hall_id>/<post_id>_card_MM.jpg` | 横並びカルーセルの各カード |
| `data/line_pc_posts/posts.jsonl` | 1行1投稿：`post_id, hall_id, run_id, capture_date, posted_date, posted_time, image, cards, height, ocr_text, fingerprint, source_pages` |
| `data/line_pc_posts/index.json` | 店舗ごとの指紋（重複判定用）と処理済みrun |

切り方：

1. 撮影ページを1本の縦長画像につなぐ（1ページ約342px＝3ノッチ上へずれる。重なりの一致で正確な量を求め、重なりの中央でつなぐ）
2. 5px以上の余白で部品に分け、部品の形で判定する：中央の小さな灰色の帯＝日付区切り（「今日」「9.25(金)」）、右寄せの低い行＝投稿時刻（投稿の終わり）、緑＝自分の送信（投稿にしない）、マウスを乗せたときの「保存｜転送」帯＝無視
3. 12px以上の余白か時刻の行で投稿を区切る（同じ分に続けて届いた画像は17px間隔で時刻が最後の1枚にしか付かない）
4. 縦長画像の上端20px以内で始まる投稿は途中で切れている可能性があるので捨てる（履歴の最上部まで撮れたときを除く）
5. 64bit の画像指紋（dHash）が店舗内の既存投稿とほぼ同じ（6bit以内）なら重複として捨てる

日付は区切りの帯から、時刻は右下の小さな文字のOCRから取る。OCRが崩れると `posted_date` / `posted_time` は null になる。

一覧で見る：`.venv/bin/python scripts/line_pc_gallery.py [--since YYYY-MM-DD]` で `data/line_pc_posts/gallery.html`（店舗ごと・新しい順、画像埋め込みの1ファイル）を作る。店名・OCR文字で絞り込める。

### 文字の読み取り（Mac の Vision、LLMなし）

Windows OCR は「今日」のような短い文字や小さな時刻を取りこぼすので、Mac 側で各ページを macOS 標準の Vision（端末内で動く文字認識）で読み直す。結果はページの横に `<page>.vision.json` として保存し、2回目からは読み直さない（初回は約3,000ページで7分ほど）。

```
swiftc -O tools/vision_ocr.swift -o build/vision_ocr   # 最初に一度だけ（build/ は git 対象外）
```

毎日の撮影は前回の続きから撮るので、最初の投稿の上に日付の区切りが写らないことがある。そうした投稿には、同じ店舗の前回の撮影で最後に見えた日付を付ける。

### 複数枚の投稿

- **1枚ずつ続けて届いた画像**：同じ分に届いた画像は17px間隔で並び、時刻は最後の1枚にしか付かない。12px以上の余白で区切るので1件ずつになる。
- **同時に届いた複数枚（横並びカルーセル）**：収集側は3ノッチずつスクロールするので、高さ約340pxのカルーセル行は必ずどこかのページに丸ごと写る。そのページで「<」で先頭に戻してから「>」を押して帯を撮る。「>」1回で動く幅は一定ではない（最大632px、端に近いと短い）ので、Mac側で隣り合う帯の重なりを毎回測って横につなぎ（動いていない帯は捨てる）、明るさで白い隙間を見つけてカードごとに切る。1枚の帯に丸ごと写ったカードも足し、同じカードは1回だけ残す（`<post_id>_card_NN.jpg`）。同じ行が複数ページに写っていれば、丸ごと写り帯の多いものを使う。カルーセル投稿の重複判定は1枚目のカードで行う（行の見た目はLINEが覚えている横位置で変わるため）。
- **同じ日に何度も撮った場合**：店舗ごとに、その日の最新の撮影だけを使う。`--rebuild` で `data/line_pc_posts/` を作り直せる。
- **縦に並んだ複数枚（リッチメッセージ）**：1投稿の1枚画像として扱う。PC版LINEでは「スマートフォンでのみ確認可能」で開けないため、画面の切り抜きがそのまま最良の画像になる。

### 店舗ごとの時系列サイト

```
.venv/bin/python scripts/line_pc_site.py        # -> data/line_pc_site/（git対象外）
python3 -m http.server 8765 -d data/line_pc_site
```

`matrix.html` は店舗×投稿日の一覧表（各セルに60pxの小さな画像、クリックで拡大。横並びは枚数バッジつき）。`index.html` に店舗一覧（最新投稿日・件数・日数・Type・送信の有無）、`stores/<hall_id>.html` に日ごと（新しい順）の投稿を並べる。画像は幅300pxのWebP（品質38）に圧縮し、遅延読み込みする（1件あたり約15KB）。
