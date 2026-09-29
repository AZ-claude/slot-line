# LINE店舗追加マニュアル（作業者向け）

パチンコ店の公式LINEを専用Android端末で友だち追加し、各店舗の「最新情報」の取り方を分類するための手順書です。
AIでも人でも、このページだけ読めば作業できるように書いています。**迷ったら止めて、ownerに聞いてください。**
他のAIに作業を依頼するときの文面は [LINE_ONBOARDING_AGENT_PROMPT.md](LINE_ONBOARDING_AGENT_PROMPT.md) にあります。

---

## 0. この作業のゴール

店舗ごとに次の4分類のどれかを決め、記録ファイルに残すことです。

| 分類 | 意味 | 日次運用 |
| --- | --- | --- |
| **Type A** | LINEにリッチメニューがない／収集に使えるボタンがないと確認済み | 受信メッセージを見るだけ |
| **Type B** | 「最新情報」ボタンを押すとLINEのトークに返信が来る | 受信を見る＋毎日ボタン（または文字送信）で取りに行く |
| **Type C** | 「最新情報」ボタンを押すと外部サイト（P-WORLD、DMMぱちタウンなど）が開く | 受信を見るだけ。URLは参考として記録 |
| **unresolved** | 上のどれとも決められない | 受信を見るだけ |

**一番大事なルール：「見えない＝ない」ではありません。** 証拠がなければ `unresolved` のままにします。無理に分類しないでください。

---

## 1. 全体の流れ（1日分）

```
① 端末の確認（縦向き・画面ON）
② 今日の対象店舗を選ぶ（1日20件まで）
③ 友だち追加スクリプトを実行（本人確認つき）
④ 撮れたトーク画面の画像を見て、メニューのボタン名を読む
⑤ 「最新情報」系のボタンがある店だけ、1回だけ押して結果を見る
⑥ 結果を review ファイルに書く
⑦ policy表と collector 登録リストを作り直す
⑧ テストを通して commit / push
```

---

## 2. 絶対にやってはいけないこと

| 禁止事項 | 理由 |
| --- | --- |
| LINEでメッセージ（文字）を送る | 店舗への送信になる。文字送信の検証はownerが手で行う |
| 「認証」「許可する」（LIFF同意画面）を押す | 個人情報の提供になる。出たら「キャンセル」かBackで閉じ、記録だけする |
| 店舗・アカウントのブロック、トーク削除 | 取り消せない。必要ならownerに頼む |
| 本人確認できない店舗の友だち追加 | 別店舗を登録してしまう |
| 同じ店舗のボタンを2回以上押す／分からないボタンを片っ端から押す | 総当たりは禁止。1店舗1回まで |
| 端末の設定変更（自動回転など） | ownerの端末設定。向きがおかしければownerに頼む |
| 1日に20件を超える新規追加、LINE IDでプロフィールを何度も開くこと | LINEの「検索回数の上限」に達し、丸1日以上追加できなくなる（実際に起きた） |
| passive collector や Scheduler の変更 | このマニュアルの範囲外 |
| `adb … input tap` などで画面を手で押す（スクリプトを使わない操作） | 座標がずれると別のトーク（個人の会話）を開く。**実際に起きた。** 端末操作はこのマニュアルのスクリプトだけで行う。例外は §3-3 の点灯と、Back キーだけ |
| スクショの座標でトーク一覧の行を開く | 一覧は新着順に動くので、古いスクショの座標は別の人のトークを指す |
| 店舗以外のトーク（個人・グループ）の画面を保存・commitする | **このリポジトリは公開**。個人の会話が世界中に見えてしまう。間違って開いたらすぐBackで閉じ、何も保存しない（スクリプトは店名が違えば保存しない） |
| トーク一覧の画面（`_chatlist.xml` やスクリーンショット）を証拠フォルダに置く | 一覧には個人の連絡先が写る。スクリプトは一覧を一時フォルダにしか保存しない。自分で一覧のスクショを撮らない |

---

## 3. 準備（毎回、作業の最初にやる）

作業場所はMacの `~/projects/slot-line` です。端末へは Mac → Windows(SSH) → ADB の経路でつながっています。

### 3-1. 端末がつながっているか

```bash
/tmp/codex-adb-bridge/adb devices
```

`HQ615G150D  device` と出ればOK。出なければownerに連絡。

### 3-2. 端末が縦向きか

```bash
/tmp/codex-adb-bridge/adb -s HQ615G150D shell dumpsys display | grep -m1 -o "mCurrentOrientation=[0-9]"
```

- `mCurrentOrientation=0` → 縦向き。OK
- それ以外 → **横向き。作業しないでownerに「端末を縦にしてください」と頼む。**
  横向きだとリッチメニューが画面に出ず、誤って「メニューなし」と判断してしまいます。

### 3-3. 画面が真っ黒なとき

端末がスリープしています。次で点灯できます（ロック画面はありません）。

```bash
/tmp/codex-adb-bridge/adb -s HQ615G150D shell input keyevent KEYCODE_WAKEUP
```

---

## 4. 作業手順

### Step 1：今日の対象店舗を選ぶ

候補一覧は `data/surveys/line_target_candidates_kanagawa_2026-09-26.json` です。
`status` が `pending` で、まだどの `line_onboarding_batch*.json` にも載っていない店舗を、上から順に最大20件選びます。

```bash
python3 - <<'EOF'
import json, glob
cands = json.load(open("data/surveys/line_target_candidates_kanagawa_2026-09-26.json"))["candidates"]
registered = {t["hall_id"] for t in json.load(open("data/line_targets.json"))["targets"]}
tried = {r["hall_id"] for f in glob.glob("data/surveys/line_onboarding_batch*.json") for r in json.load(open(f))["records"]}
todo = [c for c in cands if c["status"] == "pending" and c["hall_id"] not in tried and c["hall_id"] not in registered]
print("残り", len(todo))
today = todo[:20]
print(",".join(c["hall_id"] for c in today))
for c in today: print(c["hall_id"], c["store_name"], c["line_tokens"])
EOF
```

出てきたカンマ区切りの `hall_id` を次のStepで使います。
**20件の中にLINE IDが複数ある店舗があると、その分だけ検索回数が増えます。多ければ件数を減らしてください。**

### Step 2：友だち追加（本人確認つき）

バッチ番号 `NN` と今日の日付を決めて実行します（例：`batch04_2026-10-01`）。1店舗2〜3分かかります。

```bash
python3 scripts/onboard_line_targets.py onboard \
  --candidates data/surveys/line_target_candidates_kanagawa_2026-09-26.json \
  --hall-ids <Step1のhall_id> \
  --output data/surveys/line_onboarding_batchNN_<日付>.json \
  --evidence-dir data/surveys/line_onboarding_batchNN_<日付>_evidence
```

スクリプトがやること：

1. 店舗のLINE IDでプロフィールを開く
2. 本人確認：次のどれかに当てはまるときだけ友だち追加する
   - プロフィールのP-WORLDリンクが、hall masterのP-WORLDページと同じ
   - 店名が同じ（空白、全角半角、末尾の「店」の有無は無視）
3. トーク画面を開き、画像（`.jpg`）と画面構造（`.xml`）を保存する

1行に1店舗の結果が出ます。

| 出力 | 意味 | 次にやること |
| --- | --- | --- |
| `"result": "onboarded"` | 追加成功 | Step 3へ |
| `identity_unverified` | 名前が一致せず、追加していない | **ownerに「LINEの〇〇はhallの△△と同じ店ですか？」と聞く**（§6） |
| `dialog:…表示できません` | そのIDは使えない | 記録するだけ |
| `unknown_screen` | リンクが開けなかった | 記録するだけ |
| `"stopped": "friend_add_blocked"` | **LINEの追加制限にかかった** | **その日は作業終了。** 24時間以上空けて、翌日1件だけ試す |

owner確認で「同じ店」と言われた店舗は、LINE上の名前を添えて再実行します。

```bash
python3 scripts/onboard_line_targets.py onboard --retry-failed \
  --owner-confirmed-name "<hall_id>=<LINE上の名前>" \
  --candidates data/surveys/line_target_candidates_kanagawa_2026-09-26.json \
  --hall-ids <hall_id> \
  --output data/surveys/line_onboarding_batchNN_<日付>.json \
  --evidence-dir data/surveys/line_onboarding_batchNN_<日付>_evidence
```

### Step 3：トーク画面の画像を見て、メニューのボタン名を読む

`..._evidence/<hall_id>.jpg` を1枚ずつ開きます（**画像を見られるAI、または人が行ってください**）。
画面下半分の大きな画像がリッチメニューです。ボタン名は画像の中の文字なので、目で読むしかありません。

それぞれの店舗を次のどれかに振り分けます。

| 見えたもの | 振り分け |
| --- | --- |
| 「最新情報」「最新情報はコチラ」「NEWS」「毎日21時更新 最新情報」などのボタン | **A：押してみる対象**（Step 4） |
| 最新情報系のボタンがない（台データ、フロアマップ、X、P-WORLDなどだけ） | **B：`reviewed_no_latest_label`**（押さない） |
| リッチメニューが画面に出ていない（入力欄だけ） | **C：メニュー未表示**（押さない。§4 Step 3-2へ） |
| 判断に迷うボタン（「お知らせ」「要チェック」など） | **ownerに聞く** |

注意点：

- **メニュー上端のバー**（例「☆最新情報はこちら☆」「メニュー▼」）は開閉スイッチで、ボタンではありません。
- 「最新情報」と書いてあっても、**Xのマークつき**（X公式に飛ぶ）や**オープンチャット**行きのものは押しません。`reviewed_no_latest_label` にして、備考に書きます。

#### Step 3-2：メニュー未表示の店舗

1回の撮影だけでは「メニューなし」と決められません。追加の撮影をします（押す操作はしません）。

```bash
python3 scripts/line_chat_snapshot.py --out data/surveys/line_onboarding_batchNN_<日付>_evidence/absence_recheck \
  "<hall_id>|<トーク画面の店名>"
```

出力の `rich_menu_node` と `menu_bar` が `false`、`composer` が `true` なら、登録時の撮影と合わせて3回とも「メニューなし」なので `absent_confirmed`（Type A）にできます。1回でもメニューが見えたら `present` です。

### Step 4：「最新情報」ボタンを1回だけ押す

必ず **4-1 → 4-2 → 4-3 → 4-4** の順で行います。4-1 を飛ばさないでください。

#### 4-1：押す位置を決める

`..._evidence/<hall_id>.jpg`（Step 2 で撮った画像）を開き、「最新情報」ボタンの**真ん中**の座標を読みます。

- 画像は横720 × 縦1496 ピクセルです。左上が (0,0) です。
- メニューは画面の下の方（だいたい y=870〜1355）にあります。
- 大きいボタンでも、端ではなく中央を選びます。

#### 4-2：押さずに確認する（dry-run）

```bash
python3 scripts/line_richmenu_tap.py --dry-run --out /tmp/slot-line-dryrun \
  "<hall_id>|<LINE ID>|<トーク画面の店名>|<x>|<y>|<ボタンに書いてある文字>"
```

- 店名は、トーク画面の上に出ている名前をそのまま書きます（例：`ＺＡＰ 舟倉店` のように全角・空白も同じに）。
- 出力の `header_ok` と `tap_inside_menu` が**両方 `true`** であることを確認します。
- `/tmp/slot-line-dryrun/<hall_id>_dryrun.jpg` を開き、次の2点を**目で確認**します。
  1. 正しい店舗のトーク画面である
  2. 決めた (x, y) の位置に「最新情報」ボタンがある（x は左から、y は上からのピクセル）
- `chat_not_found_in_talk_list` が出たら**そこで止めて報告**します。座標でトーク一覧の行を開こうとしないでください。
- dry-run の画像は `/tmp` に置いたままにし、commit しません。

#### 4-3：本番（1回だけ押す）

4-2 と**同じ文字列**で、`--dry-run` を外して実行します。

```bash
python3 scripts/line_richmenu_tap.py --out data/surveys/line_onboarding_batchNN_<日付>_evidence/actions \
  "<hall_id>|<LINE ID>|<トーク画面の店名>|<x>|<y>|<ボタンに書いてある文字>"
```

同じ店舗を2回実行しても、2回目は `already_executed` になって押されません（`action_results.jsonl` で管理しています）。

#### 4-4：結果を判定する

`actions/<hall_id>_post_action.jpg` を開いて判定します。

| 押した後の画面 | action_result | 分類 |
| --- | --- | --- |
| トークに店舗から画像やメッセージが届いた | `line_reply` | **Type B** |
| P-WORLD、DMMぱちタウン、店舗サイトなどが開いた | `external_web` | **Type C**（URLは `post_action.xml` の `https://…` を記録） |
| Xアプリなど別アプリが開いた（`other_app` に名前が出る） | `external_app` | unresolved |
| 「認証」「許可する」の画面が出た | `unknown`（`blocked_by: liff_consent_required`） | unresolved。**押さずに閉じる**。ownerに報告 |
| くるくる（読み込み中）のまま | **まだ決めない** | 下の「読み込み中だったとき」を行う |
| 何も変わらない（読み込み中でもない） | `unknown` | unresolved |

**読み込み中だったとき：** 2〜5分待ってから、押さずに撮り直します。

```bash
python3 scripts/line_chat_snapshot.py --out data/surveys/line_onboarding_batchNN_<日付>_evidence/reply_recheck \
  "<hall_id>|<トーク画面の店名>"
```

店舗の画像やメッセージが写っていれば `line_reply` です。`reply_recheck` の画像も `evidence_refs` に入れます。それでも何もなければ `unknown` にします。

**Type B で、自分側（右側・緑）の吹き出しに文字が出た場合**（例「最新情報」）は、文字送信でも同じ返信が来る可能性があります。**自分で送らず**、ownerに「〇〇店に『最新情報』と1回送ってみてください」と頼みます。同じ返信が来たら `text_trigger_verified: true` にします。

### Step 5：review ファイルに書く

バッチごとに `data/surveys/collection_policy_batchNN_<日付>_review.json` を作ります。既存の `collection_policy_batch02_2026-09-27_review.json` が見本です。

```json
{
 "schema_version": 1,
 "review_id": "collection_policy_batchNN_<日付>_review",
 "policy_id": "collection_policy_batchNN_<日付>",
 "source_onboarding": "data/surveys/line_onboarding_batchNN_<日付>.json",
 "reviewed_at": "<日付>",
 "timezone": "Asia/Tokyo",
 "not_onboarded": { "<hall_id>": "理由を1行で" },
 "stores": { }
}
```

`stores` には店舗ごとに次のどれか1つを書きます。

**(1) 最新情報系ボタンなし**

```json
"<hall_id>": {
 "rich_menu_status": "present",
 "menu_review_status": "reviewed_no_latest_label",
 "visible_menu_labels": ["台データ", "フロアマップ", "X"],
 "latest_action_label": null
}
```

**(2) ボタンを押した（Step 4）**

```json
"<hall_id>": {
 "rich_menu_status": "present",
 "menu_review_status": "latest_label_observed",
 "latest_action_label": "最新情報",
 "action_mapping": {
  "executed": true,
  "executed_at": "<action_results.jsonl の triggered_at>",
  "visible_action_label": "最新情報",
  "action_result": "line_reply",
  "content_observed": true,
  "external_url": null,
  "rich_menu_emitted_text_observed": false
 },
 "evidence_refs": [
  "…/actions/<hall_id>_pre_action.jpg",
  "…/actions/<hall_id>_post_action.jpg",
  "…/actions/<hall_id>_post_action.xml",
  "…/actions/action_results.jsonl#<hall_id>"
 ],
 "notes": "何が起きたかを1文で"
}
```

- `action_result` は Step 4 の表の値を入れます。
- 返信や遷移を実際に見たときだけ `"content_observed": true` にします。何も起きなかったときは `false` です。
- `external_web` のときは `external_url` にURLを入れます。
- LIFF同意画面が出たときは、`action_mapping` に `"blocked_by": "liff_consent_required"` を足します。

**(3) メニュー未表示（まだ確定していない）**

```json
"<hall_id>": {
 "rich_menu_status": "not_observed",
 "menu_review_status": "menu_not_displayed",
 "menu_visual_review_required": true,
 "latest_action_label": null
}
```

**(4) メニューなし確定（Step 3-2で3回確認済み）**

```json
"<hall_id>": {
 "rich_menu_status": "absent_confirmed",
 "menu_review_status": "absent_confirmed",
 "latest_action_label": null,
 "evidence_refs": ["…/absence_recheck/<hall_id>_snap.jpg", "…/absence_recheck/<hall_id>_snap_1.xml", "…/absence_recheck/<hall_id>_snap_2.xml"]
}
```

**(5) ownerが判断した場合**：`action_mapping` に `"observed_by": "owner"` を足すか、Type Aなら `"no_collection_action_confirmed": true, "confirmed_by": "owner"` を書きます。`notes` に「owner が〇月〇日に△△と判断」と残してください。

### Step 5.5：commit 前の自己チェック（必須）

review を書き終えたら、店舗ごとに次の表を作り、作業報告に貼ります。**1つでも「いいえ」があれば直してから進みます。**

| hall_id | 分類 | 根拠の画像（パス） | その画像で結果が見えるか | 押した回数 |
| --- | --- | --- | --- | --- |

チェック項目：

- [ ] Type B の店舗：`post_action.jpg` または `reply_recheck` の画像に、店舗からの返信が**写っている**
- [ ] Type C の店舗：`post_action.jpg` に外部サイトが写っていて、`external_url` が入っている
- [ ] unresolved の店舗：理由（`verification_status` / `notes`）が書いてある
- [ ] Type A の店舗：メニューなしの確認が3回そろっている（登録時＋`absence_recheck` 2回）
- [ ] 押した回数はどの店舗も 0 か 1
- [ ] 証拠フォルダに、店舗以外のトーク画面・トーク一覧の画面・`_chatlist.xml`・`_dryrun.jpg` が**入っていない**

```bash
git status --short data/surveys | grep -E "_chatlist|_dryrun|talklist" && echo "NG: 入れてはいけないファイルがある" || echo OK
```

- [ ] `action_results.jsonl` に店舗以外の名前が残っていない

### Step 6：policy表と collector 登録リストを作り直す

```bash
python3 -m scripts.active_acquisition_policy \
  --onboarding data/surveys/line_onboarding_batchNN_<日付>.json \
  --review data/surveys/collection_policy_batchNN_<日付>_review.json \
  --output data/surveys/collection_policy_batchNN_<日付>.json

python3 scripts/onboard_line_targets.py registry
```

1行目の出力で、分類ごとの件数（`type_a_passive` など）が確認できます。2行目で `data/line_targets.json`（collectorが読む登録リスト）が更新されます。

証拠ファイルが全部あるかも確認します（`[]` と出ればOK）。

```bash
python3 -c "
import json,os,sys
t=json.load(open(sys.argv[1]))
print([p for r in t['stores'] for p in r['evidence_refs'] if not os.path.exists(p.split('#')[0])])" data/surveys/collection_policy_batchNN_<日付>.json
```

### Step 7：テストして commit / push

```bash
python3 -m unittest tests.test_active_acquisition_policy tests.test_onboard_line_targets tests.test_line_daily tests.test_raw_storage tests.test_regression_targets tests.test_pia_runner
```

`OK` なら、今回作ったファイルだけを add します（`git add -A` は使わない。昔の未追跡ファイルが大量にあるため）。

```bash
git add data/line_targets.json data/surveys/line_onboarding_batchNN_<日付>.json data/surveys/line_onboarding_batchNN_<日付>_evidence data/surveys/collection_policy_batchNN_<日付>.json data/surveys/collection_policy_batchNN_<日付>_review.json
git commit -m "onboard batchNN (<件数> stores)"
git push origin HEAD
```

最後に、ownerへ次を報告します。

- 追加できた件数
- 分類ごとの件数
- ownerに聞きたいこと（名前の不一致、LIFF、判断に迷うボタン）

---

## 5. 判定の早見表

```
メニューが見える？
├─ 見えない → 3回確認して全部なし → Type A（absent_confirmed）
│             1回でも見えた／確認不足 → unresolved（menu_visual_review_required）
└─ 見える → 「最新情報」系ボタンある？
     ├─ ない → unresolved（reviewed_no_latest_label）※Type Aにはしない
     └─ ある → 1回押す
          ├─ LINEに返信 → Type B
          ├─ 外部サイト → Type C
          └─ 同意画面／別アプリ／無反応 → unresolved（ownerに報告）
```

---

## 6. ownerに聞くこと（自分で決めない）

- LINE上の店名とhallの店名が違う（例「パサージュ弘明寺駅前店」と「PASSAGE 弘明寺駅前店」）
- 1つのLINE IDが複数店舗に載っている
- 「LINEが新アカウントに変わりました」などの移行案内がある
- 「お知らせ」「要チェック」「毎日更新」など、最新情報かどうか迷うボタン
- LIFFの同意画面が出た
- 文字送信（text trigger）を試したい
- 同じ名前のトークが一覧に2つ並んでいる
- 端末が横向き、自動回転がONに戻っている

---

## 7. 困ったとき

| 症状 | 原因と対処 |
| --- | --- |
| `friend_add_blocked`／「友だち追加できませんでした」 | LINEのID検索回数の上限。**その日は終了。** 24時間以上あけ、翌日まず1件だけ試す |
| スクリーンショットが真っ黒 | 端末がスリープ中。§3-3で点灯 |
| リッチメニューが写らない、画面が横長 | 端末が横向き。ownerに縦にしてもらう |
| `.xml` が0バイト、`chat_not_found_in_talk_list` が続く | 画面構造の取得（uiautomator）が一時的に失敗している。数十秒待って再実行。直らなければ行座標を指定（Step 4） |
| `TimeoutExpired`（adbが止まる） | Windows経由の接続が一時的に詰まっている。`adb devices` で確認して再実行 |
| 押した後に「認証」画面のまま | Back で閉じる（`adb … shell input keyevent KEYCODE_BACK`）。**許可は押さない** |
| 通知パネルが開いてしまった | Back で閉じる |

---

## 8. 引き継ぎ（2026-09-30 05:00 時点）

- **collector登録店舗：110**（`data/line_targets.json`）
- **まだ追加していない候補：147店舗**（Step 1のスクリプトで確認）
- **分類済みのpolicy表：** 既存41店舗、batch00〜03（`collection_policy_batch0*_*.json`）
  - batch02：Type A 0 / B 6 / C 6 / unresolved 14（MONACO桜木町・PIA横須賀中央は撮り直しで返信を確認し Type B に訂正済み）
  - batch03：Type A 0 / B 1 / C 0 / unresolved 9
- **LINE ID検索の使用：** 2026-09-30 は4回使用済み

### 次の人がやること（新規追加はしない）

どれも友だち追加済みなので、LINE ID検索は使いません。

**1. ボタン押下の再試行（3店舗）**

前回は、スクリプトの不具合でトーク一覧から見つけられず、押せていません。不具合は直り、2026-09-30 に dry-run で3店舗とも `header_ok` / `tap_inside_menu` が true になることを確認済みです。
Step 4 の 4-2 → 4-3 → 4-4 を行い、`collection_policy_batch03_2026-09-29_review.json` の該当店舗を書き換えます。

| hall_id | トーク画面の店名 | ボタン | 座標（dry-run確認済み） |
| --- | --- | --- | --- |
| sukuramburu-taya-ten | スクランブル田谷店 | 最新情報はここからチェック! | 360, 1215 |
| maruhan-sagamihara-ten | マルハン相模原店 | 最新情報 | 185, 995 |
| kik-na-totsuka-ten | キコーナ戸塚店 | 最新情報 | 240, 995 |

LINE ID の欄は `data/line_targets.json` の `line_source_key` を使います（マルハン相模原店も同じ）。

**2. マルハン川崎桜本店のメニュー再確認**

Step 3-2 の `line_chat_snapshot.py` を実行します（トーク画面の店名は `マルハン川崎桜本店`）。

- 登録時と合わせて3回ともメニューがなければ `absent_confirmed`（Type A）
- 1回でもメニューが写れば、画像を見て Step 3 の振り分けをやり直す

**3. Step 5.5 の自己チェック → Step 6 → Step 7**

### ownerの確認待ち

- ニラク平塚黒部丘店：短縮リンク先のプロフィールで店名が読み取れず、本人確認できていない。ownerがLINE上の名前を確認できたら `--owner-confirmed-name` で追加する
- ダイナム相模原店の旧アカウント `@fxl9564y`：ownerの判断で、そのまま残す

### 追加できなかった店舗（記録済み）

- batch03：ザ シティ/ベルシティ元住吉店（リンクが開けない）、アビバ新杉田店（IDが「表示できません」）

## 9. 関係するファイル

| ファイル | 中身 |
| --- | --- |
| `scripts/onboard_line_targets.py` | 候補作成（candidates）・友だち追加（onboard）・登録リスト作成（registry） |
| `scripts/line_richmenu_tap.py` | 最新情報ボタンを1回押して記録 |
| `scripts/line_chat_snapshot.py` | トーク画面の撮り直し（押さない） |
| `scripts/active_acquisition_policy.py` | review から policy 表を作る |
| `data/line_targets.json` | collector が読む登録店舗リスト |
| `data/hall_id_canonical_map.json` | 旧hall_id → hall masterのID の対応 |
| `data/surveys/line_target_candidates_kanagawa_2026-09-26.json` | 追加候補一覧 |
| `data/surveys/line_onboarding_batch*.json` | 友だち追加の記録 |
| `data/surveys/collection_policy_*_review.json` | 画像レビュー・ボタン押下の記録（人・AIが書く） |
| `data/surveys/collection_policy_*.json` | 最終的な店舗別policy表（自動生成） |
| `docs/LINE_DAILY.md` | 日次運用とpolicyの説明 |
