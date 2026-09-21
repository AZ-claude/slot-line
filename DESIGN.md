# slot-line 全体設計

## 1. 目的

LINE公式アカウントから配信される店舗情報を日次で収集し、元データ（RAW）として保存したうえで、公開用データへ変換する仕組みを作る。

最初から多数店舗・多数パターンに対応せず、YAGNIで以下の2パターンだけをPoC対象とする。

1. **通常配信型**
   - 友だち登録しておけば、店舗側から自動でメッセージや画像が届く。
2. **操作要求型**
   - 「最新情報」等の指定文字列を送ると情報が届く店舗を第一候補とする。
   - 文字列送信で代替できない場合だけ、Android側のUI操作を取得トリガーにする。

PoCで「日次で自動取得できる」「RAWとして残せる」「後段で公開用データへ変換できる」ことを確認してから対象店舗・取得方式を増やす。

---

## 2. 基本方針

### 2.1 取得と公開を完全に分離する

LINEで受信した画像・文章をそのまま一般公開する設計にはしない。

処理を以下の4段階に分離する。

```text
店舗公式LINE
   ↓
[1] 取得
   ↓
[2] RAW保存
   ↓
[3] 解析・正規化
   ↓
[4] 公開用データ
```

RAWは解析・再検証用の非公開ソースとして扱う。

公開側では、RAWから抽出した事実・構造化情報・分析結果のみを利用する。

---

## 3. 想定運用環境

### 3.1 LINEアカウント

普段使いのメインLINEは使用しない。

**LINE収集専用のサブアカウント**を用意し、対象店舗の公式LINEのみを登録する。

### 3.2 Android

専用Android端末をLINE収集用として利用する。

主な役割は、WindowsからADBで起動・対象指定されたLINE上でのtrigger送信、返信の構造取得、LINE標準操作による画像保存である。PIA町田ではリッチメニューではなく、AndroidのLINE URL schemeによる`text_trigger`を使う。文字列送信で代替できない場合だけ、リッチメニュー等のUI操作を行う。

通常運用ではユーザーがAndroidを操作しない。ADB接続、LINE起動、対象確認、trigger、返信取得、画像保存をWindowsから制御する。

### 3.3 Windows

常時運用Windows PCを収集の中心にする。

想定役割:

- ADBによるAndroid制御とtrigger実行
- `adb pull`、RAW保存、取得ログ保存
- 日次タスク実行
- 後段の解析・正規化
- エラー検知

Windows版LINEデスクトップは通常運用のランタイム依存にしない。必要な場合だけ、対象確認済みの送信debug/fallbackとして使う。

Macは開発用とし、実運用・E2EはWindowsで確認する。

---

## 4. 全体アーキテクチャ

```text
                    ┌──────────────────────┐
                    │ LINE公式アカウント   │
                    └──────────┬───────────┘
                               │
                   ┌───────────┴───────────┐
                   │                       │
             通常配信型               操作要求型
                   │                       │
                   │                 Android LINE URL text_trigger
                   │                 （代替できない場合のみ
                   │                  Android UI trigger）
                   │                       │
                   └───────────┬───────────┘
                               │
                        LINEメッセージ受信
                               │
                        ┌──────▼──────┐
                        │ RAW Collector│
                        └──────┬──────┘
                               │
                   ┌───────────▼───────────┐
                   │ RAW Storage           │
                   │ text / image / meta   │
                   └───────────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Normalize / Analyze │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Public Data         │
                    └─────────────────────┘
```

---

## 5. PoC対象

### 5.1 パターンA: 通常配信型

対象は1アカウントのみ。

#### 想定フロー

```text
公式LINEから配信
  ↓
専用LINEアカウントで受信
  ↓
Windows側で新着を検知
  ↓
本文・画像・日時・店舗情報を取得
  ↓
RAW保存
```

人間によるボタン操作は不要。

---

### 5.2 パターンB: 操作要求型

対象は1アカウントのみ。

例: 指定文字列「最新情報」を送ると情報が返る店舗。リッチメニューに同じ文字列のボタンがある場合でも、まず文字列送信との等価性を確認する。

#### 想定フロー

```text
指定時刻
  ↓
WindowsからADBでAndroid LINE oaMessage URLを起動
  ↓
Android UI階層で対象公式アカウントとプリフィル文字列を完全一致確認
  ↓
Android UIAutomatorで送信
  ↓
公式LINE返信
  ↓
Android側でADB/UI Automatorにより返信検知
  ↓
本文・画像をRAW保存
  ↓
画像はLINE標準保存 → adb pull → Windows保存
```

oaMessage URL方式が実機で完全E2E成立しない場合は、Windows版LINEの `text_trigger` UIA送信をfallbackとして使う。ただし、対象トークを機械確認できないまま現在のWindowsトークへ送信する方式は本番採用しない。

リッチメニュー操作と文字列送信が等価でない店舗だけ、`android_ui_trigger` を採用する。座標タップは通常方式にしない。

PIA町田の実機確認では、Windows UIA送信による返信の構造取得、画像保存、`adb pull`、RAW manifest生成までの最小E2Eを1回成立させた。また、oaMessage URL方式では対象選択・プリフィル・送信までを実機確認した。URL方式の返信を含む完全E2Eはこの更新では再試験していない。Windows-only取得方式の追加調査でも、Windows側で返信本文・時刻・送信元・画像境界・元画像を安定して対応付ける経路は成立しなかった。したがって、Windows版LINEは本番ランタイムから外し、Android URL方式を本番候補の第一候補とする。

```text
Windows = ADB制御 + pull + RAW保存
Android = 対象選択 + trigger送信 + 返信構造取得 + LINE画像保存
fallback: Windows UIA text_trigger送信（対象確認が別途成立する場合のみ）
```

Windows UI Automationは入力操作には使うが、返信本文の取得元とはしない。返信の構造取得と画像取得はAndroid側を正とする。

Windows-only取得の調査は1回で打ち切る。`linedesktopnvda` の標準チャット書き出しは本文・時刻・送信者の参考になるが、画像メッセージのバイナリと境界を同じ構造で返さない。`Data\\db\\*.edb` は標準SQLiteとして読めず、`Cache` の画像らしいファイルもメッセージメタデータとの対応が未成立である。よって、本設計ではWindows内部DBの復号、プロセス内部介入、OCRによる取得を前提にしない。

---

## 6. Android自動操作

### 6.1 PoC

まずはADBによる端末確認、画面ON、LINE起動、返信検知を試す。店舗トリガーはAndroidのLINE URL schemeによる`text_trigger`を第一候補とし、Windows版LINEは本番経路に含めない。

想定:

```text
画面ON
↓
LINE起動
↓
返信到着をuiautomatorで検知
↓
対象メッセージを構造取得
```

通常運用でユーザーにロック解除・LINE起動・対象トーク表示・ボタン押下・文字入力を依頼しない。初回認証、OSのセキュアロック、RSA再認証、LINE再認証だけは人間操作の例外とする。

### 6.2 無人復旧の実機確認（2026-09-21）

設定変更なしで、Windowsから次を確認した。

- ADBサーバーの停止・起動後、RSA再認証なしで`device`へ復帰した（論理再接続）。
- LINEを`force-stop`してADBから起動し、`MainActivity`前面・ADB`device`を確認した。
- 画面OFF後、ADBのWAKEUPで`Asleep`から`Awake`へ戻した。
- 復帰時の通常スワイプ式キーガードをADBの標準ジェスチャーで閉じ、LINEを再起動して前面へ戻した。読み取り上はPIN・パターン・パスワードが設定されていないため、セキュア認証の突破は行っていない。
- 物理USB抜き差し後、RSA再認証なしで`device`へ復帰し、LINE URLの対象・プリフィルを確認した。
- Windows再起動後は、ユーザーによるWindows再起動後にADB・LINE URLの対象・プリフィルを確認した。Windows自動再起動だけでの復帰は成立しなかった。
- Android本体再起動後は約98秒でADBへ復帰したが、キーガード解除にユーザー操作が必要だった。解除後はLINE URLの対象・プリフィルを確認した。

Windows再起動とAndroid本体再起動は完全無人復旧に未成立である。本体再起動後のキーガード解除、画面ロック方式変更、既存タスク変更は行っていない。`stay_on_while_plugged_in=2`は変更せず、LINEはDoze whitelistに存在した。

通常運用は「Windowsジョブ開始 → ADB確認 → LINE起動 → Android URL trigger → Android構造取得・画像保存 → `adb pull` → Windows RAW保存」とする。セキュアロックが有効な端末では、再起動後の解除が必要になった時点だけ人間介入とし、ロック突破は行わない。

### 6.3 本運用時の改善候補

座標固定は以下で壊れる可能性がある。

- LINEアップデート
- ポップアップ表示
- リッチメニュー開閉状態
- 画面スクロール状態
- Android解像度変更
- 通知やOSダイアログ

必要になった場合のみ以下を検討する。

- Android UI Automator
- uiautomator2
- Appium
- Accessibilityベースの自動操作

PoC段階では過剰実装しない。

---

## 7. 店舗Adapter

店舗ごとに情報の出し方が異なることを前提とする。

差分は店舗Adapterに閉じ込め、後段は共通処理にする。

当面のAdapter分類は次の3種類に限定する。

- `passive`: 操作不要で自動配信される。
- `text_trigger`: 指定文字列を送信すると返信される。AndroidのLINE URL schemeからの送信を第一候補とし、Windows版LINE UIA送信はdebug/fallbackに限定する。
- `android_ui_trigger`: テキスト送信等で代替できず、Android UI操作が本当に必要な場合だけ使う。

新規店舗では、まずリッチメニュー操作と特定文字列送信が等価かを実機で確認する。等価なら `text_trigger` を採用し、`android_ui_trigger` や座標依存のリッチメニュー操作は採用しない。

実機確認後の例:

```text
store_a
  type: passive
  action: none

pia_machida
  type: text_trigger
  action: send_text
  text: "最新情報"
  trigger_source: android_line_url
  reply_source: android_uiautomator
  image_source: android_line_download

store_c
  type: android_ui_trigger
  action: tap_menu
  reason: text_trigger_not_equivalent
```

将来パターンが増えても、Collectorや公開用変換ロジックへ店舗固有処理を混ぜない。

---

## 8. RAWデータ

### 8.1 RAWに保存するもの

最低限:

- store_id
- source
- captured_at
- received_at（取得可能なら）
- trigger
- original text
- original image
- message/order identifier
- acquisition status
- error details
- collector version

例:

```json
{
  "store_id": "pia_machida",
  "source": "official_line",
  "captured_at": "2026-09-20T21:05:32+09:00",
  "trigger": "text_trigger",
  "text": "LINEで受信した元テキスト",
  "images": [
    "raw/2026-09-20/pia_machida/001.jpg"
  ],
  "status": "success"
}
```

### 8.2 保存構造例

```text
data/
  raw/
    2026-09-20/
      pia_machida/
        messages.json
        001.jpg
        002.jpg
      store_a/
        messages.json
        001.jpg
```

保存形式は実装時に変更可能だが、RAWを後から再解析できることを優先する。

---

## 9. 正規化・解析

RAW取得と解析を同一処理にしない。

RAWはまず原形で保存し、その後に解析する。

想定処理:

- テキスト解析
- OCR
- 画像理解
- 店舗名正規化
- 対象日抽出
- 機種名抽出
- 告知カテゴリ判定
- 示唆内容の構造化
- 信頼度・根拠の保存

正規化例:

```json
{
  "store_id": "pia_machida",
  "target_date": "2026-09-21",
  "information_type": "machine_notice",
  "machines": [
    "マイジャグラーV"
  ],
  "source": "official_line",
  "observed_at": "2026-09-20T21:05:32+09:00"
}
```

---

## 10. 公開用データ

公開サイトからRAWへ直接アクセスさせない。

公開対象は、元LINEの画像・全文転載ではなく、RAWから抽出した事実・構造化結果を基本とする。

例:

```text
PIA町田
9/20 21:05 公式LINE更新
マイジャグラーVに関する告知を確認
```

将来的にはslot側の他データと結合する。

例:

```text
公式LINE告知
    ↓
対象日の機種/イベント候補
    ↓
みんレポ実績
    ↓
告知と結果の相関分析
```

---

## 11. 著作権・利用上の設計方針

このリポジトリでは法律判断を自動化しないが、システム設計として以下を基本にする。

- LINEから取得した元画像・元文章は原則非公開RAWとして扱う。
- 公開側では事実・数値・構造化情報・独自分析を中心にする。
- RAW保存領域をWeb公開ディレクトリに置かない。
- 元画像をそのまま大量掲載する設計にはしない。
- 必要最小限の対象アカウント・頻度で取得する。
- 将来運用拡大時にはLINE利用規約・各権利関係を再確認する。

「RAWを取得できること」と「そのまま公開してよいこと」は別問題として扱う。

---

## 12. 日次処理

### 通常配信型

```text
受信
↓
新着検出
↓
RAW保存
↓
重複チェック
↓
取得ログ
```

### 操作要求型

```text
指定時刻
↓
対象店舗Adapter実行
↓
Android操作
↓
応答待機
↓
新着検出
↓
RAW保存
↓
取得ログ
```

解析・公開用変換は取得成功後に独立ジョブとして実行できるようにする。

---

## 13. 冪等性・重複防止

日次処理は再実行可能にする。

同じ配信を二重保存しないため、以下の組み合わせから一意キーを作る想定。

- store_id
- message timestamp
- normalized text hash
- image hash
- acquisition date

完全なmessage IDが取得できる場合はそれを優先する。

---

## 14. 失敗状態

成功/失敗を曖昧にしない。

最低限:

- success
- no_message
- trigger_failed
- line_not_ready
- android_unreachable
- extraction_failed
- image_save_failed
- partial
- unknown

「何も保存されなかった」だけでは正常と失敗を区別できないため、必ず実行ログを残す。

---

## 15. ログ

日次で以下を追えるようにする。

- 実行日時
- store_id
- Adapter
- trigger開始/終了
- Android接続状態
- 新着件数
- テキスト取得数
- 画像取得数
- RAW保存先
- エラー
- retry回数

---

## 16. Windows再起動耐性

本番運用はWindows常時稼働機を前提とする。

最低限確認する。

- Windows再起動後も必要サービスが復帰する
- LINEが利用可能な状態へ戻れる
- Android接続が復帰する
- タスクスケジューラが動く
- 前日未取得分を検知できる
- 同一日の再実行で重複しない

Windows版LINEのログイン状態は本番経路の前提にしない。物理USB再接続は実機PASSとした。Windows再起動は今回ユーザーによる再起動後に復帰確認、Android本体再起動はキーガード解除後に復帰確認となったため、いずれも完全無人復旧のPASSとはしない。

---

## 17. PoCの合格条件

最初の目標は「サイトまで完成」ではない。

以下を満たせばPoC合格とする。

1. 通常配信型1アカウントからRAW取得できる。
2. 操作要求型1アカウントでtext_trigger送信→Android返信取得→RAW取得できる。
3. テキストと画像の両方を保存できる。
4. 店舗・日時・取得方式を追跡できる。
5. 同一処理を再実行しても重複しない。
6. 人手なしで日次実行できる。
7. 連続運用で取りこぼしを検知できる。
8. RAWから公開用JSONを1つ生成できる。

目安として、2アカウントを1週間連続で人手介入なしに取得できれば次段階へ進む。

---

## 18. PoCではやらないこと

YAGNIのため、以下は初期対象外。

- 数十〜数百店舗対応
- 店舗設定GUI
- 汎用ノーコードAdapter
- 高度なAI示唆判定
- 自動サイト掲載
- RAW画像の公開
- 完璧なOCR
- 複雑な分散処理
- クラウド移行
- Android複数台制御
- 全LINEパターンへの先回り対応

実際に必要になったものだけ追加する。

---

## 19. 初期実装順

```text
Phase 0
専用LINE + Android + Windows版LINEを準備し、実機で取得経路を確認

Phase 1
単一アカウント・単一トークの最小E2E
Windows ADB制御 → Android LINE URL text_trigger → Android UI階層取得 → LINE標準画像保存 → adb pull → Windows RAW保存

Phase 2
text_triggerで代替できない店舗だけ、android_ui_triggerを追加

Phase 3
共通RAW schemaへ統合

Phase 4
再実行・重複防止・ログ

Phase 5
RAW → 公開用JSON変換

Phase 6
1週間連続E2E
```

---

## 20. 将来拡張

PoC完了後、必要性が確認できたものだけ追加する。

候補:

- 店舗Adapter追加
- キーワード送信型
- 多段リッチメニュー型
- OCR/画像解析精度改善
- slot本体へのデータ連携
- LINE告知とみんレポ結果の突合
- 店舗別「告知→結果」の傾向分析
- 取得失敗通知
- Android画面状態認識
- 取得対象店舗管理

---

## 21. 最終的な責務分離

```text
slot-line
  ├─ LINEから情報を取得する
  ├─ RAWを安全に保存する
  ├─ 店舗ごとの取得差分を吸収する
  └─ 公開可能な構造化データへ変換する

slot
  ├─ 他媒体データと統合する
  ├─ 日付/店舗/機種単位で分析する
  └─ ユーザー向けに表示する
```

slot-lineは「LINE収集・変換」に責務を限定し、slot本体の表示・分析ロジックを抱え込まない。

---

## 22. 現時点の決定事項

- 専用サブLINEを使用する。
- メインLINEは収集用途に使わない。
- Windows常時運用PCを中心にする。
- Windows版LINEは本番ランタイム依存にしない。WindowsはADB制御・`adb pull`・RAW保存を担う。
- Androidは対象指定、trigger、返信の構造取得、LINE標準画像保存を担う。リッチメニュー等のUI操作は、text_triggerで代替できない場合だけ使う。
- PIA町田はAndroid LINE URLの`text_trigger`を第一候補とし、Windows UIA送信は対象確認済みの場合だけdebug/fallbackにする。
- 通常日はAndroidを人間が操作しない。初回認証、セキュアロック解除、RSA再認証、LINE再認証だけを例外的な人間作業とする。
- 最初は通常配信型1件 + 操作要求型1件だけ。
- 店舗差分はAdapterとして隔離する。
- RAWを先に保存し、後から公開用データへ変換する。
- RAW画像・元文章の一般公開を前提にしない。
- 最初から多数店舗へ広げない。
- PoC成功後にslot本体との連携を検討する。
