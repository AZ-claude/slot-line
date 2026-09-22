# Phase 0: LINE収集環境の成立確認

## この記録について

- 実施日: 2026-09-20〜2026-09-21 (Asia/Tokyo)
- 対象: 専用LINEアカウント、専用Android、Windows常時運用PC
- 目的: Windows版LINEとAndroidの同一アカウント運用、ADB操作、A/B同期、RAW取得方式を実機で確認する
- 方針: 実機で確認できない項目をPASSにしない。認証の自動突破は行わない。

## 実施環境

- Mac: 開発機。ローカル作業ツリーは `main` `04086c4`（`origin/main` と一致）。
- Windows運用機: 既存 `~/.ssh/config` と既存鍵でSSH接続成功。Windows 11 Home 10.0.26200 / 64-bit
- Windowsのホスト名・ユーザー名: 公開記録には保存しない
- Android: Sony `SO-41B` / Android 13 / SDK 33。ADB serialは公開記録には保存しない

Windows側では既存のTask Schedulerや起動設定を変更していない。

## 現時点の結論

Phase 0 のうち、WindowsへのSSH接続、Windows側ツールの存在、ADBによるAndroid接続、画面ON、LINEパッケージ起動、専用アカウントのWindows版LINEログイン、Aトークの両端末表示まで確認できた。

Aの23:00本文については、Android `uiautomator` から本文・時刻・メッセージ行の構造データを取得できた。一方、Windows UI AutomationではAトークの構造要素は列挙できたが、本文・送信元・時刻の値は取得できなかった。Bは応答可能時間帯に再試験し、リッチメニュー押下と手入力 `最新情報` の返信構造・画像ハッシュが一致した。リッチメニュー個別要素は未露出だが、返信取得の観点ではリッチメニュー操作を廃止し、テキスト送信を第一候補にできる。

Phase 0のデータ取得経路は実機で成立したため、Phase 0はデータ経路について完了扱いとする。さらにPhase 1のPIA町田 `text_trigger` E2E（Windows送信→Android取得→画像保存→Windows RAW保存）を1回確認した。ただし、応答可能時間帯の境界は未特定であり、無人本番運用・定期実行まで完了とはしない。

追加のWindows-only取得調査（`linedesktopnvda`、`AppData\\Local\\LINE`、既存OSSを対象）でも、Windowsだけで返信本文・時刻・送信元・画像・RAW manifestまで完結する経路は成立しなかった。このため、PC-only PASSにはせず、`Android = trigger＋取得`、`Windows = 制御＋保存` を現行の正式構成として維持する。

`DESIGN.md` は `origin/main` から取得し、614行を全文確認済み。以後は同設計のPhase 0/Phase 1の境界と、YAGNI方針を正とする。

## 確認結果

| 項目 | 結果 | 根拠・備考 |
| --- | --- | --- |
| `DESIGN.md` 全文確認 | 確認済み | `origin/main` の `04086c4` にある614行を確認した。 |
| Windows版LINEのインストール | 確認済み | `winget list --name LINE` でMicrosoft Store版 `8.3.0.3189` を確認し、ログイン済みの `LINE.exe` 稼働も確認。 |
| Chrome版ではなくデスクトップ版 | 確認済み | WindowsのLINEデスクトップアプリ登録とMicrosoft Store ID `XPFCC4CD725961` を確認。 |
| 専用LINEアカウントのPCログイン | 確認済み | ユーザーがログインを完了し、Windows版LINEの通常トーク一覧を確認。LINEプロセスも稼働中。 |
| 自動ログイン設定 | 未確認 | Windows版LINEのログイン画面を確認していない。 |
| Windows再起動後の復帰 | human_intervention_required | 自動再起動後はWindowsが復帰せず、ユーザー再起動後にADB・URL target/prefillを確認。 |
| LINEプロセス再起動後の復帰 | 確認済み | `force-stop`後にADBからLINEを起動し、`MainActivity`前面を確認。 |
| ログアウト状態の検知 | 未確認 | 状態表示・プロセス・通知の観測方法を試していない。 |
| Android版LINEのメイン端末利用 | 部分確認 | ユーザーがA/Bを登録済み。ADB確認時は端末がロック画面で、トーク一覧・ログイン状態を画面確認できていない。 |
| USB debugging / ADB | 確認済み | WindowsのADB 37.0.1でSO-41Bが状態 `device` として認識され、物理USB再接続・Windows再起動後・Android再起動後もRSA再認証なしで復帰した。 |
| 画面ON・LINE起動の安全なADB操作 | 確認済み（現時点） | `KEYCODE_WAKEUP` と `monkey -p jp.naver.line.android 1` を実行し、`mWakefulness=Awake` とLINE前面Activityを確認。 |
| A: 通常配信のAndroid/Windows同期 | 部分確認 | Aトークは両端末で開ける。Androidでは本文・時刻・送信元を取得できたが、Windows UIAでは値を取得できず、4項目の完全照合は未確認。 |
| B: リッチメニューの表示と操作 | 確認済み（個別要素は未露出） | 応答可能時間帯に手動押下で返信を取得。個別の `最新情報` 要素は露出せず、UI指定ではなく座標候補のみ。テキスト送信と等価だったため、リッチメニュー操作は廃止候補。 |
| B: 操作結果のWindows同期 | 未確認 | 今回はAndroid側の返信比較に限定し、Windows UIAからの返信本文取得は行っていない。 |
| Windows側RAW取得 | 未合格 | AトークのUIA構造は取得できるが、本文・送信元・時刻・画像ファイル対応が値として露出しない。内部DBのSQLite直読みにも失敗。 |
| Android側RAW取得 | 確認済み | A本文に加え、B返信の画像をLINE標準ダウンロードで `/sdcard/Pictures/LINE` に保存し、Windowsへ `adb pull`。Android/WindowsのSHA-256一致を確認。 |
| RAW取得方式 | 実機決定 | `Android = 操作＋取得`、`Windows = 制御＋保存`。時間条件の境界とWindows送信経路の本番耐性は別の残課題。Android日本語入力は不要。 |
| Phase 0完了判定 | 完了扱い（データ経路） | A本文、B返信構造、画像RAWのWindows保存経路、PIA町田のリッチメニュー廃止候補を実機確認。時間帯境界・Windows送信の本番耐性・定期実行はPhase 0後の残課題。 |
| Phase 1 PIA町田E2E | 1回成立 | Windows UIA入力欄へ正しい `最新情報` を設定してEnter、Androidで12:28返信を構造取得、画像保存、Windows `adb pull`、SHA-256一致まで確認。 |

## 追加実機調査: ログイン後

2026-09-20、ユーザー操作後にA/Bだけを対象として確認を再開した。

### Windows版LINE

- 専用アカウントのログイン完了と通常トーク一覧の表示をユーザーが確認した。
- Windows上では `LINE.exe` が稼働中で、実行中バージョンは `26.4.2.3957` だった。
- `Data\db` 配下に `*.edb` のチャット関連ファイルが存在する。
- 主データ候補をPython標準のSQLite読み取り専用接続で開いたところ `file is not a database` となった。標準SQLiteとしてそのまま機械取得する方式は成立していない。
- `Cache` 配下には拡張子のないハッシュ名ファイルが多数ある。画像・本文・送信元・受信時刻との対応付けはまだ確認できず、キャッシュ直読みによるRAW方式は採用していない。
- GUIの画面要素はSSHセッションから安定して取得できていない。Windowsの対話デスクトップ上でのGUI/UI Automation確認が必要である。

### Android側（初回状態確認）

- ユーザーが登録した対象はA（エムアンドエム溝口）とB（PIA町田）の2件だけである。
- A/Bのトーク一覧・配信内容を確認する時点で、端末はロック画面だった。ロック解除は自動化せず、ユーザー操作に任せる。
- ADBで画面起動とLINE起動は再度成立したが、ロック画面のためメッセージ内容・送信元・時刻・リッチメニューは未確認である。
- 初回のロック状態では、Aの通常配信がAndroid/Windows双方に届いたことは未確認。Bの手動リッチメニュー操作と返信同期も未確認。

その後、ユーザーがAndroidをロック解除してLINEのトーク一覧を表示した状態で、UI階層からA/Bの表示領域を特定して読み取り確認した。

- A（エムアンドエム溝口）とB（PIA町田）が同じAndroidのトーク一覧に表示された。
- Aは23:00の未読テキスト1件。送信元はエムアンドエム溝口で、本文は友だち登録へのお礼と最新情報を定期配信する旨だった。確認したメッセージには添付画像はなかった。
- Bは23:01の未読画像メッセージ2件。送信元はPIA町田で、少なくとも画像メッセージが表示された。
- 初回確認時点ではBのリッチメニューのボタンは押していなかった。後続の手動押下では送信済み `最新情報` が表示されたが、Bからの返信は表示されなかった。
- Windows側で同じメッセージの本文・画像・時刻・送信元を画面または取得データとして照合する作業は未完了である。

### RAW方式の暫定判定（A本文試験前）

Windows内部DBの標準SQLite直読みによる取得は不成立だった。A本文のUI Automation確認とAndroid側の取得可能性比較前だったため、この時点では `Android = 操作` / `Windows = 取得・保存` または `Android = 操作＋取得` / `Windows = 制御＋保存` のどちらも採用しなかった。その後のA本文試験の判定は下記に記録する。

## UI Automation / Accessibility PoC

ユーザーの要求に従い、既存Task Schedulerタスクを変更せず、現在ログイン中の対話ユーザーでのみ動く一時タスクを作成してUIAを実行した。試験後に一時タスクとスクリプトは削除した。

### Windows版LINE（Aトークを開いた状態）

- 現在ログイン中の対話セッションでだけ動く一時Task Schedulerタスクを作成し、LINEのUIAルート `AllInOneWindow` 以下84要素を列挙できた。既存タスクは変更せず、試験後に一時タスクとスクリプトを削除した。
- `AllInOneChatPanel`、`ChatMessagePanel`、`ChatMessageView`、`LcText`、`LcImage` など、トーク本文・画像に相当し得る構造クラスは見える。
- しかし、列挙したAトークの要素では、ルートのウィンドウ名 `LINE` 以外の `Name`、`ValuePattern`、`TextPattern` の値が空だった。Aの本文、`23:00`、送信元名は取得できなかった。
- `LcImage` も構造要素として1件見えたが、受信画像のファイルパス・メッセージ対応・画像データは取得できなかった。
- よって、Windows UI AutomationによるA本文の構造取得は未合格。GUI座標、手動コピー、OCRによる代替は採用しない。

### Android側（Aトークを開いた状態）

- 一時的に `stay_on_while_plugged_in` を元の `0` から `2` に変更して試験し、終了後に `0` へ復元した。画面タップや送信操作は行っていない。
- `uiautomator dump` はLINEのAトーク画面を取得し、76ノードを返した。OCR・スクリーンショット読取りは使用していない。
- `android.widget.TextView` / `jp.naver.line.android:id/chat_ui_message_text` に、Aの実際の23:00メッセージ本文が複数行テキストとして露出した。親の `chat_ui_row_text_message` にも同じ本文が `content-desc` として露出した。
- `android.widget.TextView` / `jp.naver.line.android:id/chat_ui_row_timestamp` から `23:00` を取得できた。
- `chat_ui_row_text_message` の1つの親行（bounds `[81,233][910,532]`）と、その子の本文ノード（bounds `[81,244][910,517]`）が得られ、メッセージ単位の境界を特定できた。送信元はヘッダー `jp.naver.line.android:id/header_title` の `エムアンドエム溝口` として取得できた。
- 今回のAメッセージはテキスト配信で、同じメッセージ行内に画像添付ノードはなかった。見えた `chat_ui_row_thumbnail` は公式アカウントのプロフィール画像であり、本文メッセージの添付画像との対応はこのA実験では判定できない。Bの画像メッセージは、A試験完了までは操作しない方針のため未確認。
- よって、Android `uiautomator` によるAの本文・時刻・メッセージ境界の構造取得は確認済み。画像の元ファイル取得と画像メッセージへの対応は未確認。

### A本文試験時点のRAW方式判定

- Windowsは内部 `.edb` を標準SQLiteとして読めず、UIAでも本文値を取得できなかったため、Windowsを本文RAW取得係にする根拠は得られなかった。
- AndroidはA本文・時刻・行境界を `uiautomator` から取得できたため、現段階の最小候補は `Android = 操作＋取得`、`Windows = 制御＋保存` とする。
- これはAのテキストに対する暫定候補であり、Bの手動操作・ADB単発操作、B返信の同期、画像メッセージの元データ取得を確認するまで、Phase 0全体のRAW方式を最終確定しない。

## Bリッチメニューおよび画像RAWの実機試験

2026-09-21、B「PIA町田」だけを対象に確認した。Windows UI Automationの深掘りは行っていない。

### 初回手動押下（応答なし時間帯）

- 押下前のAndroid `uiautomator dump` は95ノードで、Bトークとリッチメニュー全体を取得できた。
- リッチメニュー全体は `jp.naver.line.android:id/chat_ui_row_receive_rich_container` と内部 `android.widget.ImageView` の領域 `[9,760][711,1149]` として見えた。別の親フレームには `content-desc="アプリ"` があった。
- 「最新情報」は `text`、`content-desc`、専用 `resource-id` のいずれにも露出せず、個別ボタンとしては特定できなかった。対象領域をリッチメニュー画像全体より狭く安定取得する根拠は得られなかった。
- ユーザーが「最新情報」を手動で1回押した後のダンプは103ノードとなり、送信済みメッセージ `最新情報` が `jp.naver.line.android:id/chat_ui_row_text_message` と `chat_ui_message_text` に現れた。時刻は `11:49`、既読表示も確認できた。
- 手動押下後に新しい受信本文・画像・返信メッセージは確認できなかった。返信がないため、B操作PoCは未成立とし、ADBによる自動1回押下には進まなかった。
- 現時点で自動化する場合はUI要素指定ではなく、リッチメニュー画像上の座標指定しか候補がない。ただし手動返信が成立していないため、座標の自動操作はまだ実施しない。

### 初回画像RAW試験

- Bの23:01配信は、UI階層上で画像領域 `[9,274][711,663]` と時刻 `23:01` を持つ `chat_ui_row_receive_rich_container` として特定できた。内部は `android.widget.ImageView` だが、通常画像添付用の保存UIやファイル識別子は露出しなかった。
- その領域を1回開くとLINE画像ビューアではなく、Google Playの「PIA公式アプリ」ページが開いた。アプリのインストールは行っていない。
- LINEへ戻った後、同じ領域を1回長押ししたが、LINE標準の画像保存メニューは表示されなかった。
- したがって、このBサンプルは通常の受信画像ではなくリンクカードであり、`LINE画像 → Android通常ストレージ → adb pull → Windows RAW` の保存経路は成立していない。private領域、root、OCR、スクリーンショットRAWには進んでいない。

### 初回B試験時点の判定（応答なし時間帯）

- Bリッチメニューの表示と、手動押下により送信メッセージが生成されることは確認済み。
- Bからの返信、返信のAndroid構造取得、Windows同期、受信画像の通常ストレージ保存は未確認または未成立。
- この時点ではPhase 0完了条件を満たしていなかった。後続の応答可能時間帯試験結果は次節に記録する。

### 応答可能時間帯での再試験（2026-09-21）

#### 時間条件

- 初回は11:49にリッチメニュー押下相当の `最新情報` が送信されたが、返信は表示されなかった。
- 応答可能状態で再試験したところ、リッチメニュー押下では12:09に返信が表示され、手入力 `最新情報` では12:13に返信が表示された。
- したがって、11:49の無応答と12:09/12:13の応答という事実は確認できたが、応答可能時間帯の境界はまだ特定できない。1時間おきの定期実装や本番Task Scheduler化には進まない。
- ユーザーが確認した「毎日21時更新」という表示は、更新時刻・配信時刻を示す可能性があるが、今回12:09/12:13にも同じ返信が得られたため、返信受付可能時間と同一とは判断しない。表示文言と応答可能時間の関係は未確定とする。

最小試験計画は次のとおりとする。

1. `20:50`、`21:00`、`21:10` に各1回だけ、同じ `最新情報` 要求を送る。
2. 各回で要求時刻、返信の有無、最初の返信時刻、返信構造、画像SHA-256を記録する。
3. 翌日に同じ3点のうち少なくとも `21:00` を1回再確認し、日付依存・一時的状態を切り分ける。
4. 境界が分かるまで、定期実行・大量試行・リトライは実装しない。

#### リッチメニューと文字送信の比較

- リッチメニュー押下後の返信は、12:09の同一時刻を持つ次の2メッセージだった。
  - `jp.naver.line.android:id/chat_ui_row_receive_rich_container` のリッチカード1件
  - `jp.naver.line.android:id/chat_ui_row_image` / `content-desc="添付写真"` の画像1件
- 画像メッセージの境界は `chat_ui_row_image_balloon_root`、画像領域は `[81,336][531,853]`、時刻ノードは `chat_ui_row_timestamp` の `12:09` だった。返信に本文テキストノードはなかった。
- 手入力 `最新情報` 後の返信も、12:13の同一構造だった。リッチカード1件、`chat_ui_row_image` の画像1件、画像時刻 `12:13`、同じメッセージ境界属性を確認した。
- 両返信画像をLINE標準のダウンロードで保存し、リッチメニュー側 `1789960271565.jpg` と文字送信側 `1789960490989.jpg` をWindowsへ `adb pull` した。Windows側の保存先は `C:\Users\Public\slot-line-phase0-B-image-raw.jpg` と `C:\Users\Public\slot-line-phase0-B-text-image-raw.jpg`。両ファイルはサイズ `378170` bytes、SHA-256 `884D76B3B0AC86A511FC707F700C9E15C1A754307D2C708E25A735BDC3C304B2` で一致した。
- 表示文字列だけでなく、返信の構造と画像バイナリが一致したため、今回の実機サンプルではリッチメニュー押下と文字送信は等価と判定する。ただし送信イベントの内部postback値まではUI階層から確認できないため、内部イベントまで同一とは断定しない。

#### PIA町田Adapterの最小候補

- `最新情報` はリッチメニュー個別要素として露出せず、座標指定に依存する。一方、文字送信で同じ返信が得られたため、PIA町田Adapterではリッチメニュー座標タップを廃止候補とし、テキスト送信を第一候補とする。
- PIA町田ではAndroidから日本語を入力せず、Windows版LINEから `最新情報` を送信する。Androidは返信の `uiautomator` 取得、LINE標準画像保存、`adb pull` を担当する。
- Androidの `adb shell input text "最新情報"` は日本語入力で `NullPointerException` となったが、PIA町田の本番候補では不要と判断した。この問題は追跡しない。

### B再試験時点の判定

- A本文の構造取得、B返信の構造取得、受信画像のAndroid通常ストレージ保存、Windowsへの `adb pull`、画像ハッシュ一致まで実機で成立した。
- Bのリッチメニュー操作は、個別UI要素を取得できず座標依存だが、文字送信と同じ返信を返すため、収集経路としては不要と判断する。
- RAW取得方式は `Android = 操作＋取得`、`Windows = 制御＋保存` に正式決定する。時間条件の境界とWindows送信経路の本番耐性は、Phase 0後の最小残課題として記録する。Android日本語入力問題は追わない。

## Phase 0 / Phase 1運用方針の更新

今回の実機結果に基づき、`DESIGN.md` の店舗Adapter分類と初期実装順を更新した。

### Adapter分類

- `passive`: 操作不要で通常配信を受ける。A「エムアンドエム溝口」をこの分類の確認対象とする。
- `text_trigger`: 指定文字列を送信すると返信される。B「PIA町田」は `text_trigger`、文字列は `最新情報` とする。
- `android_ui_trigger`: テキスト送信等で代替できない場合だけ採用する。現在、PIA町田には採用しない。

新規店舗は、リッチメニュー操作と特定文字列送信の等価性を最初に確認し、等価なら座標依存のリッチメニュー操作を追加しない。

### Phase 1のPIA町田最小E2E

```text
Windows版LINE
  ↓ text_trigger: 「最新情報」をUIA ValuePatternで設定してEnter
公式LINE返信
  ↓ Android uiautomatorで検知・構造取得
LINE標準ダウンロード
  ↓ Android通常ストレージ
adb pull
  ↓
Windows RAW保存
```

- Windows UIAは本文取得には使わず、入力欄へのプログラム送信だけに使う。Windows UIAから返信本文を取得できるとは判定しない。
- Androidの日本語入力は不要であり、PIA町田のためにADB日本語入力問題を解決しない。
- 今回の1回E2Eでは、Windows UIAの `AutoSuggestTextArea` にUnicodeコードポイントから構成した `最新情報` を設定し、Enterを送信した。Androidで12:28の返信を検知し、画像を `/sdcard/Pictures/LINE/1789961449058.jpg` へ保存、Windowsへpullした。
- この手動構成の保存先は `C:\Users\Public\slot-line-phase1-pia-text-trigger-raw.jpg`、サイズは `378170` bytes、Android側とSHA-256一致を確認した。これは方式確認用の一時保存であり、本実装の保存先にはしない。
- 最初の一時スクリプトはWindows PowerShellのソース文字コードにより文字化け送信になったため、正しいE2Eとは扱わない。ASCIIのコードポイント構成へ修正後、正しいコードポイント `U+6700 U+65B0 U+60C5 U+5831` を確認して再実行した。

### Phase 1の範囲外

- Androidリッチメニュー座標タップの本番化
- Androidからの日本語入力方式の開発
- OCR、AI解析、多店舗対応、Task Scheduler本番化
- Windows UIAによる返信本文取得の再調査

### Phase 1 PIA町田 Windows送信E2E実機結果

- Windows版LINEの `AutoSuggestTextArea` をUI Automationで特定し、`ValuePattern` により入力欄へ設定できることを確認した。
- 最初の一時スクリプトはWindows PowerShellのソース文字コード解釈により文字化けした文字列を送信した。これは失敗試験として記録し、E2E成功には含めない。
- 修正版では日本語をソースへ直接書かず、ASCIIのUnicodeコードポイントから `U+6700 U+65B0 U+60C5 U+5831`（`最新情報`）を構成した。設定後のUIA `ValuePattern` readbackが一致し、Enterを送信した。人間操作、手動コピー、手動ペーストは行っていない。
- Windows UIAは送信後のトーク本文を読み取れないため、送信済み本文の画面値をWindows側で再取得することは未成立。送信成功は、直前のUIA readbackとAndroid側の返信到着で確認した。
- Android側では `PIA町田` の12:28返信を検知した。返信はリッチカード1件と画像1件で、画像は `jp.naver.line.android:id/chat_ui_row_image`、`content-desc="添付写真"`、メッセージ境界は `chat_ui_row_image_balloon_root`、時刻は `chat_ui_row_timestamp` の `12:28` だった。
- 画像をLINE標準ダウンロードでAndroidの `/sdcard/Pictures/LINE/1789961449058.jpg` に保存し、Windowsの `C:\Users\Public\slot-line-phase1-pia-text-trigger-raw.jpg` へ `adb pull` した。サイズは `378170` bytes、Android/WindowsのSHA-256は `884D76B3B0AC86A511FC707F700C9E15C1A754307D2C708E25A735BDC3C304B2` で一致した。
- 実行後はAndroidの一時スリープ抑制を元の `0` に戻し、一時Task Schedulerタスク・スクリプト・UIダンプを削除した。既存タスクは変更していない。

### Phase 1最小実装の固定とLive E2E

実機で成功した方式だけを `scripts/run_pia_machida.py` に固定した。対象はPIA町田1店舗のみで、リッチメニュー操作・Android日本語入力・Windows本文取得は実装していない。

```text
Android baseline取得
  ↓
Windows UIA ValuePatternで「最新情報」を設定してEnter
  ↓
Android LINE起動・PIA町田トーク表示
  ↓
uiautomatorで新しいrich_card + image行を検知
  ↓
LINE標準ダウンロード → /sdcard/Pictures/LINE
  ↓
adb pull → data/raw/YYYY-MM-DD/pia_machida/
```

2026-09-21、Windows運用機で実装後のLive E2Eを人間操作なしで1回実行し、`success` になった。

- Windows UIAの一時対話タスクは、ASCIIのUnicodeコードポイントから `最新情報` を構成し、`ValuePattern` readback一致後にEnter送信した。
- Androidでは12:44の返信をrich card 1件 + image 1件として取得し、メッセージ境界は `[0,155][720,806]` と `[0,822][720,1347]` だった。
- LINE標準ダウンロード後にAndroidの `/sdcard/Pictures/LINE` で新規ファイルを特定し、Windowsへ `adb pull` した。
- リポジトリ設計のRAWは `data/raw/2026-09-21/pia_machida/response_001.jpg`、378170 bytes、SHA-256 `884d76b3b0ac86a511fc707f700c9e15c1a754307d2c708e25a735bdc3c304b2` として保存した。`manifest.json` には必須項目、返信時刻、メッセージ種別・境界、構造ダンプ名を記録している。
- 同じ実装の最初の試行はADB出力をWindows既定CP932で読み取ったため `extraction_failed` になった。ADB subprocessのUTF-8置換読み取りへ修正後の1回だけをLive E2E成功とする。失敗記録も同日の `manifest.json` に残している。
- 再実行重複防止は、pull後のSHA-256を同日 `response_*.jpg` と比較し、一致時は新しい画像ファイルを増やさない。
- 実行後の一時Task Schedulerタスクは0件、Androidの `stay_on_while_plugged_in` は元の `0` に復元され、既存タスクは変更していない。

### Phase 1の判定

PIA町田について、`Windows = text_trigger送信 + Android制御 + RAW保存`、`Android = 返信構造取得 + LINE標準画像保存` の最小E2Eを1回再現できたため、Phase 1のPIA町田部分をPASSとする。ただし、Windows版LINEのPIA町田トークをUIAだけで選択・本人確認する処理は今回の成功手順に含めていないため、運用機では対象トークを表示した対話セッションを前提とする。対象トークを確認できないまま別トークへ送信しない追加ガードは、次の最小改善候補とする。

次に進める作業は、応答可能時間帯の最小試験計画と、LINE再起動・Windows再起動後のログイン状態／ログアウト検知の確認である。多店舗化、Task Scheduler本番登録、OCR、AI解析、slot連携はまだ行わない。

### Android LINE URL scheme PoC

LINE Developers公式仕様にある次のURL形式を対象に、PIA町田で検証した。

```text
https://line.me/R/oaMessage/{Percent-encoded LINE ID}/?{Percent-encoded text}
```

公式仕様では、Android/iOSで公式アカウントのトークを開き、指定テキストを入力欄へ設定できる。Windows版LINEはこのURL schemeの対象外である。PIA町田の公開されている公式LINE追加リンクから、LINE ID候補 `@030pwlwx` を確認し、UTF-8 percent-encodeした実行URLを組み立てた。

2026-09-21の実機PoCでは、Windows運用機からADBでURLを起動し、次を実機確認できた。

- UI階層のヘッダーが `PIA町田` と完全一致した。
- `jp.naver.line.android:id/chat_ui_message_edit` の値が `最新情報` と完全一致した。
- `jp.naver.line.android:id/chat_ui_send_button_image` のcontent-descが `送信` で、UIAutomatorのboundsから送信できた。
- Windows版LINEの現在表示トークには依存しなかった。Androidはホーム画面からURLだけで対象トークへ遷移した。
- Android日本語IME、OCR、固定座標による店舗探索は使用していない。

ただし、20:35（Asia/Tokyo）に送信した1回は、90秒以内に返信がなく `response_timeout` となった。送信後のAndroid UIには20:35の `最新情報` 送信行だけが増え、対象トーク誤認による送信ではないことは確認できた。これはURL方式の対象選択・プリフィル・送信のPASSであり、応答を含む完全E2EのPASSではない。PIA町田の応答可能時間帯で追加送信するまで、本番方式を `Windows = 制御＋保存` / `Android = trigger＋取得` に正式変更しない。

URL方式の最初の試行はURL解決直後の一時的なUIAutomator空ルートで送信前に終了した。実装はこの状態を再試行し、対象・プリフィルを確認できない場合は送信しないfail closedとした。実行記録は同日の `data/raw/2026-09-21/pia_machida/manifest.json` に残している。

## Windows側の準備調査

2026-09-20に既存SSH設定から読み取り中心で確認した。

| 調査項目 | 実測結果 |
| --- | --- |
| Windows版LINE | `winget list --name LINE` で `LINE / XPFCC4CD725961 / 8.3.0.3189 / msstore`。更新可能版は8.7.0.3303と表示されたが、勝手に更新していない。 |
| LINE起動状態 | 初回調査時にWindows側LINEプロセスはなかった。SSHからAppUserModelId経由のGUI起動を試したが、ログイン画面を確認できなかった。 |
| ADB | Android SDK Platform-Tools 37.0.1-15733141。`adb devices -l` でSO-41Bを認識。 |
| Python等 | Python 3.12.8、Node.js 24.13.0、Git 2.55.0.windows.2、Windows PowerShell 5.1。 |
| Task Scheduler | サービスはRunning / Automatic。既存の `SlotDiscordBackup`、`SlotDiscordBot`、`SlotFxtwitterSyncV1` を確認。LINE/ADB用タスクは未作成。 |
| 起動設定 | StartupフォルダはAnyDeskのみ。RunキーにもLINEはない。LINEの自動起動設定は未確認・未設定。 |
| 変更の有無 | 既存タスク、レジストリ、Startup、LINE設定は変更していない。 |

LINEの実行ファイルはレジストリ上の旧来パスが存在する一方、そのパスの実ファイルは確認できなかった。`winget` のインストール登録は存在するため、まずWindowsの対話デスクトップでスタートメニューからLINEを起動し、起動不能なら公式Windows版の修復・再インストールを人間が判断する。8.3.0.3189から8.7.0.3303への更新も、ログイン前のため現時点では行わない。

## Android側の準備調査

`adb devices -l` の結果、Android端末は実際には既にUSB接続されていた。端末情報はSony `SO-41B`、Android 13 / SDK 33、USB debugging有効（`adb_enabled=1`）。LINEパッケージ `jp.naver.line.android` も存在した。

画面は調査開始時にスリープ状態だったため、次の安全操作だけを実施した。

```text
adb -s <ANDROID_SERIAL> shell input keyevent KEYCODE_WAKEUP
adb -s <ANDROID_SERIAL> shell monkey -p jp.naver.line.android 1
```

結果は `mWakefulness=Awake`、前面ActivityがLINEとなった。ただし、取得した画面キャプチャは黒画面で、ログイン状態・ロック状態・リッチメニュー表示は判定していない。認証やロック解除は行っていない。

WindowsのPlatform-Toolsは既に利用可能なので、追加インストールは不要である。Androidを再接続した際には、次を実行して状態が `device` になることを確認する。

```powershell
adb devices -l
```

## 次に必要な人間操作

SSH経由の読み取り・安全なADB操作だけではログイン認証を完了できないため、ここから先の認証はユーザーが行う。

1. Windows運用機の現在のデスクトップで、スタートメニューから `LINE` を開く。SSH経由の起動では画面表示を確認できなかったため、物理画面または既存の対話セッションで開く。
2. Android `SO-41B` の画面を物理操作で起こしてロックを解除し、LINEを表示する。
3. Windows版LINEにQRコード、メールアドレス/パスワード入力、または認証番号が表示された場合だけ、専用Android側でQR読み取り、生体認証、パスワード入力、認証番号入力を行う。
4. Windows版LINEがログイン済みのトーク一覧を表示し、Android側も専用アカウントのホーム/トークを表示できた時点で停止し、結果を知らせる。A/B公式アカウントの登録や店舗操作は、その後に別途1件ずつ行う。

認証画面が出ない、LINEが起動しない、または別アカウントが表示される場合は、その画面の状態だけを伝える。認証情報やQR画像をリポジトリ・ログへ保存しない。

## 人間が行うセットアップ手順

### Windows

1. 専用Windows PCにLINE公式のWindowsデスクトップ版をインストールする。今回のWindows機にはMicrosoft Store版が登録済みなので、まず起動可否を確認し、必要な場合だけ人間が修復・再インストールする。Chrome版は使わない。
2. 専用Androidをメイン端末としてLINEを起動した状態にする。
3. Windows版LINEを起動し、QRコード、生体認証、または登録済みメールアドレス/パスワードでログインする。
4. QRコードや認証番号が表示された場合は、専用Android側で本人確認を行う。これは人間の作業とし、自動化・回避しない。
5. ログイン画面の「自動ログイン」を有効にする。
6. Windows起動後にLINEが起動する設定は、実機での運用方針を確認してから設定する。まずはログアウトしていないこと、LINEプロセスが起動していることを人間が確認できる状態にする。

公式ヘルプでは、PC版LINEは公式サイトからダウンロードでき、ログイン画面の「自動ログイン」で次回以降の自動ログインを有効にできると案内されている。初回・再インストール時に認証番号が表示される場合があるため、そのときはメイン端末で認証する。

### Android / ADB

1. Androidで開発者向けオプションを有効にする。
2. 開発者向けオプションのUSBデバッグを有効にする。
3. AndroidをWindows PCへUSB接続する。
4. Androidに表示されるRSAデバッグ許可を、人間が端末を確認して許可する。許可を自動化しない。
5. WindowsのAndroid SDK Platform-Toolsに含まれる `adb.exe` が実行できることを確認する。
6. 次のコマンドで、状態が `device` になっていることを確認する。

```powershell
adb devices -l
```

7. 認識後に限り、画面ONとLINE起動だけを安全操作として確認する。LINEのパッケージ名は実機で確認し、固定値を盲目的に使わない。

```powershell
adb shell input keyevent KEYCODE_WAKEUP
adb shell pm list packages | findstr /i line
adb shell monkey -p <確認済みのLINEパッケージ名> 1
```

この段階では、送信ボタンの自動タップ、店舗への大量アクセス、リッチメニューの大量実行は行わない。

## A/B同期PoCの手順

専用LINEアカウントへ、次の2件だけを人間が登録する。

- A: 操作なしで通常配信が届く公式アカウント1件
- B: 指定文字列 `最新情報` の送信で返信が届く公式アカウント1件

### A: 通常配信

1. AndroidでAからテキスト1件と画像1件を受信する。
2. Androidで、受信時刻、表示された送信元、テキスト、画像の有無を記録する。
3. Windows版LINEで同じトークを開く。
4. 同じメッセージが、テキスト・画像・受信時刻・送信元の4項目で確認できるか記録する。
5. LINEプロセス再起動後にも同じトークを開き、同じ結果になるか確認する。

### B: text_trigger

1. Windows版LINEでB「PIA町田」のトークを開く。
2. UI Automationの入力欄へ指定文字列 `最新情報` をプログラム設定し、Enterで送信する。人間による入力・コピー・ペーストは使わない。
3. AndroidはADBで画面ON・LINE起動・対象トーク表示を行い、`uiautomator dump` で返信の到着を検知する。
4. 返信の本文・リッチカード・画像・時刻・メッセージ境界をAndroid UI階層から取得する。
5. 画像がある場合はLINE標準ダウンロード、Android通常ストレージ特定、`adb pull`、Windows RAW保存までを行う。

### B: android_ui_trigger（例外）

text_triggerと等価でない場合だけ採用する。PIA町田では実機比較により等価だったため、この手順は適用しない。

## 通常試験・運用時のAndroid操作規則

通常の試験・運用では、ユーザーにAndroidのロック解除、LINE起動、対象トーク表示、リッチメニュー押下、文字入力を依頼しない。まずWindowsからADB/UIAutomatorで自動実行する。

ユーザー操作を依頼してよいのは、次の場合だけとする。

- LINE初回認証
- Android再起動後にOSのセキュアロック解除が技術的に不可避な場合
- USBデバッグのRSA再認証
- LINE強制ログアウト後の再認証

自動化方法が未実装であることだけを理由に、通常操作を人間へ戻さない。

## RAW取得方式の判定基準

実機比較が終わるまでは方式を決定しない。小規模なA/Bサンプルで次を確認する。

### Windows方式の合格条件

- Windows版LINEから、テキスト・送信元・受信時刻を、画面画像へのOCRに頼らず機械的に取り出せる。
- 画像をスクリーンショットではなく、受信画像のファイルとして保存できる。
- LINEの通常起動、プロセス再起動、Windows再起動後の少なくとも各1回で同じ手順が再現する。
- フォーカス位置、ウィンドウ座標、表示倍率の偶然に依存しない。
- 取り出せないメッセージはエラーとして検知でき、黙って欠落しない。

上記を満たす場合の候補構成は `Android = 操作`、`Windows = 取得・保存` とする。

### Android方式の合格条件

- ADBで対象トークを開き、UI階層または画面キャプチャから、対象メッセージの存在とテキストを再現性をもって取得できる。
- 画像は元ファイルの取得可否を確認し、取得できない場合は画面キャプチャをRAWとして扱うことを明記する。
- 画面ON、LINE起動、対象トーク表示が人間の確認後に安全に再現できる。
- 表示状態・端末解像度・スクロール位置に依存する失敗を検知できる。

Windows方式が上記を満たさない場合の候補構成は `Android = 操作＋取得`、`Windows = 制御＋保存` とする。

A本文のテキスト取得、B返信の構造取得、画像の通常ストレージ保存、Windowsへの `adb pull` は実機で確認済みである。Windows UIAは本文取得では未合格だが、入力操作PoCは成立したため、方式は `Android = 操作＋取得`、`Windows = 制御＋保存` に正式決定した。応答可能時間帯の境界とWindows送信経路の本番耐性は、無人本番化前の残課題である。Android日本語入力はPIA町田の方式に含めない。

## ログイン耐性と検知の最小確認

認証情報を自動入力したり、認証を突破したりしない。次の4状態を実機で人間が作り、観測結果だけを記録する。

| 試験 | 確認内容 | 合格の考え方 |
| --- | --- | --- |
| 自動ログイン | LINE終了後に再起動 | 人手の再認証なしでトークが開く。 |
| Windows再起動 | Windows再起動後にLINEを起動 | 通常はログイン状態へ復帰する。 |
| LINEプロセス再起動 | LINEだけを終了・再起動 | 通常はログイン状態へ復帰する。 |
| ログアウト状態 | メイン端末のログイン中端末からPCをログアウトする等 | PCのログイン画面・認証要求を検知でき、再ログインは通知して人手に任せる。 |

公式ヘルプが挙げるサブ端末のログアウト要因には、別サブ端末からのログイン、メイン端末での認証情報変更、メイン端末からのログアウト、ネットワーク障害、一定時間操作がない場合などがある。したがって再ログインの自動突破は設計に含めず、ログアウト検知と通知を最小要件とする。

## 自動化候補と人手作業

### 人手が必要

- 専用LINEアカウントの準備とA/B公式アカウントの友だち追加
- Windows版LINEの初回ログイン、QR、生体認証、パスワード、認証番号の処理
- AndroidのUSBデバッグとRSA許可
- ログアウト・認証要求が発生した場合の再認証

### 実機成立後に自動化を検討

- Windows起動後のLINEプロセス確認とログイン画面検知
- ADBの接続状態確認、画面ON、LINE起動
- Windows版LINEへのプログラム送信とAndroid側の返信検知
- LINE標準画像保存、`adb pull`、Windows RAW保存
- 合格したRAW方式による小規模な保存と実行ログ
- ログアウト検知時の通知

## 次の最小実装

実機で上記確認が完了した後に、`DESIGN.md` のPhase 1要件に沿って次のうち必要な最小部分だけを実装する。

1. Windows `text_trigger` とAndroid返信取得を単一アカウント・単一トーク向けに固定する
2. ADB接続確認、画面ON、LINE起動、対象トーク表示の単純コマンド
3. LINE標準画像保存、RAWファイル、実行ログのローカル保存
4. `android_ui_trigger` はtext_triggerで代替できない店舗だけ追加する
5. ログアウト検知時の通知

多店舗対応、OCR、AI画像解析、slot本体連携、Web公開、高度なAdapter、Appium等の大型フレームワーク、完璧な監視基盤はPhase 0の対象外とする。

## 参照した公式資料

- [LINEヘルプ: パソコン(PC)でLINEをダウンロード・ログイン／ログアウトするには？](https://help.line.me/line/?contentId=50001182&lang=ja)
- [LINEヘルプ: サブ端末でLINEのログイン／ログアウトに問題が発生している](https://help.line.me/line/?contentId=50001462&lang=ja)
- [Android Developers: Run apps on a hardware device](https://developer.android.com/studio/run/device)
- [Android Developers: Android Debug Bridge (adb)](https://developer.android.com/tools/adb)

## Windows-only取得方式の追加調査（2026-09-21、1回限定）

### 判定

PCだけで次の全てを人間操作なしに完結する方式は、今回の実機・コード調査では成立しなかった。

```text
Windows = 送信 + 返信取得 + 画像取得 + RAW保存
```

したがって、Windows-only PASSにはしない。現在の正式構成は引き続き次とする。

```text
Windows = 制御 + 保存
Android = trigger + 返信構造取得 + 画像取得
```

既存のAndroid方式と `scripts/run_pia_machida.py` は削除・縮小していない。今回の調査では新しい取得方式の実装やTask Scheduler登録も行っていない。

### `keyang556/linedesktopnvda` のコード調査

調査対象は、2026-09-19時点のupstreamコミット `d23d5a5922b766051a51af51a97fd91acc9b2349` である。

#### OCRなしで成立している部分

- LINEの「儲存聊天（チャット保存）」を起点に、Windowsの一時ファイルへチャット書き出しを保存する。
- 保存ダイアログはWin32 APIで検出し、ファイル名を `SendMessageW`、保存ボタンを `BM_CLICK` で操作する。
- 書き出されたUTF-8テキストを `_chatParser.py` が解析する。
- パーサは日付、`HH:MM`、送信者名、本文、複数行継続を構造化する。該当コードは `_DATE_RE`、`_MSG_RE`、`parseChatFile()` で、出力要素は `type/name/content/time` である。

この部分だけなら、本文・時刻・送信者をテキストとして取得できる可能性はある。ただし、LINE標準のチャット書き出しを対象トークから開始する必要があり、画像バイナリや画像メッセージの境界を同じ構造として返す実装ではない。

#### OCRに依存する部分

- 「儲存聊天」メニューの発見・行位置・クリック対象は `chatMoreOptions.py` が画面領域を `ocrGetText()` に渡して作る。
- 画像メッセージの右クリックメニューと「另存新檔」「新增至相簿」等の画像操作候補は `messageContextMenu.py` がOCRで識別する。
- 背景キャッシュは、書き出し済みテキストを保持する一方、現在フォーカス中の吹き出しとの照合にOCR文字列を使う。`_chatCache.py` の説明にも `OCR'd text` と明記されている。
- UIAの `CurrentName`、`ValueValue`、`LegacyIAccessible`、子要素を試す実装はあるが、値が取れない場合はDisplay Model/OCRへfallbackする構成である。これは安定したメッセージAPIではない。

結論として、同アドオンは「標準チャット書き出しのテキスト解析」というOCRなしの部品を持つが、画像を含むメッセージ単位の機械取得器ではない。Message ReaderをそのままRAW Collectorとして採用できない。

#### 画像メッセージ

同アドオンは画像用メニューが存在することで画像らしさを判定し、ユーザー向けの「Save As」操作を補助する。しかし、画像の元ファイル、送信元、時刻、メッセージ境界を1つの構造レコードとして返す処理はない。AI画像説明機能は外部API送信を含むため、今回のRAW方式候補から除外した。

### Windows実機の `AppData\\Local\\LINE` 調査

調査対象のLINEプロセスはWindows版 `26.4.2.3957`。既存プロセスを停止せず、既存Task Schedulerも変更せずに、ファイル一覧・サイズ・先頭バイトなどの読み取りだけを行った。

追加確認時点でAndroidはADB状態 `device`。ユーザー希望により、USB接続中に画面をスリープさせない `stay_on_while_plugged_in=2` を維持している。今回のWindows-only調査ではこの設定を変更していない。

- `Data\\db` には `qw...edb`、`album_...edb`、`chatStats_...edb`、`keep_...edb` と主データのWAL/SHMが存在した。
- `.edb` の先頭はSQLiteの `SQLite format 3` ではなく、今回の実機では標準Python `sqlite3` の読み取り専用接続も `file is not a database` で失敗した。
- `Data` 配下に通常の `.db`、`.sqlite`、`.sqlite3` のメッセージDBは見つからなかった。
- `Cache` は416ファイル、合計約9.57MB。拡張子なしが383、`.eimg` が13、`.qmlc` が20だった。
- 最近更新された拡張子なしファイルの先頭にはJPEG（`FF D8 FF E0 ... JFIF`）およびPNG（`89 50 4E 47 ...`）のシグネチャが実際にあった。したがってキャッシュに画像バイトが置かれること自体は確認できる。
- しかし、ファイル名はハッシュ風で、今回の読み取り範囲ではPIA町田の返信、本文、送信元、時刻、メッセージ行との対応を機械的に確認できなかった。`.eimg` は一般画像の先頭シグネチャではなく、形式・対応付けも未確認である。

既知のforensics研究では、LINE Windowsの`.edb`が暗号化DBであること、画像キャッシュに暗号化と実行時キーが関係することが報告されている。ただし、バージョン差の影響が大きく、キー抽出・メモリ解析・プロセス内部への介入は今回の安全範囲外である。認証情報の抜き出し、コードインジェクション、root相当の手法は実施していない。

### 既存OSS・ツールの比較

| 候補 | 実装方式 | 今回の採否 |
| --- | --- | --- |
| `keyang556/linedesktopnvda` | LINE標準チャット書き出し＋UTF-8パーサ。メニュー・画像判定・吹き出し照合にOCR | 本文の参考にはなるが、画像付き無人RAW Collectorとしては不採用 |
| `dtwang/line-desktop-mcp` | MIT。WindowsはAutoHotkeyの座標クリックとCtrl+A/Cのクリップボード取得。履歴応答はテキストのみで、画像取得実装はない | 送信・テキスト補助の参考に留め、不採用。人間の選択操作を自動化しただけで、構造取得・画像RAWの合格条件を満たさない |
| `curzer1995-777/line-local-mcp-user-key` | MIT。ユーザー提供キーで暗号化DBを読むmacOS専用の読み取りMCP。添付ファイルはダウンロードしない | Windows対象外。キー取得・抽出を行わない方針とも合わないため不採用 |
| LINE Data Master等の製品 | WindowsローカルDB読取を謳うが、OSSではなく今回の再現可能なコード検証対象にできない | 製品導入を前提にしないため不採用 |

外部送信の有無については、`linedesktopnvda`の通常のMessage Reader経路と`line-desktop-mcp`の標準stdio経路はローカルGUI操作・ローカル出力の実装だが、後者のHTTPモードはネットワーク公開設定を持ち、既知の認証リスクもある。いずれも本プロジェクトへ導入していない。AI画像説明や外部APIはRAW取得に使わない。

### PC-only合格条件との照合

| 条件 | 結果 | 根拠 |
| --- | --- | --- |
| PIA町田へ `最新情報` を送る | 既存のWindows UIA送信PoCは成立 | これは現在表示中トーク依存の既存fallbackであり、取得方式の合格を意味しない |
| 返信を検知する | 未成立 | Windows側で対象返信を構造検知する経路は未確認 |
| 本文・時刻・送信元を構造取得する | 未合格 | 実機UIAは要素構造のみで値が空。Message Readerの書き出しテキストは画像境界を含まない |
| 画像メッセージと対応付ける | 未成立 | Cacheの画像バイトとメッセージメタデータを対応付ける根拠がない |
| 元画像または同等品質を保存する | 部分確認のみ | CacheにJPEG/PNGシグネチャはあるが、対象返信との対応・安定取得を確認していない |
| RAW manifestを生成する | 未成立 | Windows-onlyの構造取得に基づくmanifestは生成していない |

1回限定の追加調査として、ここでWindows内部形式のreverse engineeringを打ち切る。GUIスクリーンショット＋OCR、現在開いているトークへの盲目的な送信、内部DBの鍵探索はPC-only PASSの代替にしない。

### 正式方針と次の最小実装

PC-onlyは不合格。既存のAndroid方式を正式な実運用候補として維持する。

```text
PIA町田 text_trigger
  Windows: ADB制御、必要な送信制御、RAW保存
  Android: 対象trigger、返信のuiautomator構造取得、LINE標準画像保存
  Windows: adb pull、SHA-256/byte size、manifest保存
```

Android側のURL trigger実装とWindows UIA送信fallbackは残す。今回の結果を受けて、次の最小実装はWindows-only探索ではなく、既存Android経路の対象確認・ログイン状態検知・失敗状態の維持改善とする。Task Scheduler本番化、多店舗化、OCR、AI解析、slot連携はこの記録の範囲外であり、まだ開始しない。

## Windows公式機能経路の1回限定実機試験（2026-09-21、未成立）

### 試験対象と制約

既存のPIA町田トークだけを対象にした。新しいメッセージ送信、LINE内部DB・Cache解析、Windows UI Automationによる吹き出し本文取得、OCR、Task Scheduler本番登録は行っていない。Androidの既存方式は削除・変更していない。

LINE公式ヘルプ上は、Windows／Macのトーク画面上部メニューから[トークを保存]を実行でき、現在表示されている履歴だけがTXT保存対象になる。また、[写真／動画]一覧からPC保存と[メッセージに移動]ができると説明されている。

- [LINEヘルプ: トーク履歴をテキスト形式(.txt)で保存するには？](https://help.line.me/line/ios/?contentId=20007388&lang=ja)
- [LINEヘルプ: トークルームの写真⋅動画などを編集／確認するには？](https://help.line.me/line/?contentId=20008461&lang=ja)

### 実機で確認できたこと

- Windows版LINEの既存PIA町田トークを一覧から明示的に開き、既知の返信画像が画面に表示されていることを確認した。
- LINEの本文表示領域はUI Automationの子要素として公開されず、公式メニュー項目・本文・写真一覧をUIA要素として構造取得する経路は確認できなかった。検査結果はLINEのトップレベル`AllInOneWindow`のみで、本文テキストは取得していない。
- 画面上の公式メニューを1回だけ開き、[トークを保存]を選択する試験を行ったが、保存先ダイアログ、TXTファイル、TXT内容の生成を確認できなかった。
- その操作後、Androidの同じPIA町田トークのUI階層に`ブロック中`が現れ、Windows側でもPIA町田が一覧・`PIA町田`検索・`@pia_machida`検索から消えた。したがって、今回のクリックは保存操作として検証できず、公式メニューを座標で操作する方式は安全な自動化経路にならないと判断した。
- 副作用はADB/UIAutomatorでAndroid側の[ブロック解除]を実行して復旧した。復旧後のUI階層ではPIA町田のヘッダと`@pia_machida`が残り、メニュー項目も[ブロック]に戻った。新しい送信は行っていない。
- 復旧後もWindows側のPIA町田トークは自動的には一覧・検索へ戻らず、今回のWindows公式機能試験を安全に再開できる対象状態を確保できなかった。

### 試験結果

| 項目 | 結果 | 実機根拠 |
| --- | --- | --- |
| 既存トークから公式[トークを保存]を実行 | 未成立 | 保存先ダイアログまたはTXT生成を確認できず、操作後に対象状態が変化した |
| TXTから日付・時刻・送信者・`最新情報`・返信・画像エントリを解析 | 未確認 | TXTが取得できていない |
| [写真／動画]から既存画像をPC保存 | 未確認 | 対象Windowsトークを安全に再選択できなくなり、保存操作へ進んでいない |
| PC保存画像のbyte size/SHA-256を既知Android値と比較 | 未確認 | Windows画像ファイルを取得していない |
| [メッセージに移動]とTXTエントリの対応 | 未確認 | 写真一覧・TXTの両方を取得していない |
| PC-only取得方式 | **FAIL（PASSにしない）** | 5条件のうちTXT、画像、対応付け、manifestが未成立 |

今回の失敗は、LINE公式機能が仕様上存在しないという結論ではない。公式メニューの座標操作がメニュー誤選択時にアカウント状態を変更し得ること、かつUIAからメニュー・本文を機械確認できなかったことを、実機で確認した結果である。保存先・ファイル・画像ハッシュを確認できていないため、既知Android画像の`378170 bytes`／`884d76b3b0ac86a511fc707f700c9e15c1a754307d2c708e25a735bdc3c304b2`との一致判定も行っていない。

### 方針

Windows公式機能経路は今回の1回限定試験でPASSにしない。新しい座標推測、メニュー探索、アカウント状態を変更する再試行は行わない。正式構成は既存どおり次とする。

```text
Windows = 制御 + 保存
Android = trigger + 返信構造取得 + LINE標準画像保存
```

`scripts/run_pia_machida.py`、Android URL trigger、Android UIAutomator取得、LINE標準画像保存、`adb pull`は実運用候補として維持する。Windows UIA送信は対象確認済みの場合だけdebug/fallbackとし、返信本文の取得元にはしない。今回はPC-only方式の合格根拠が得られなかったため、設計変更は行わない。

## Android専用収集端末の無人運用確認（2026-09-21）

Windows-only方式の探索はコミット`b170762`で終了し、以後はAndroidをWindowsから制御する方式だけを対象にした。Windows版LINEの内部DB・Cache・UIA本文取得の再調査は行っていない。

### 変更前の設定読み取り

設定変更前に、Windowsの既存SSH設定・既存ホスト経由で運用機から実機を読み取った。

| 項目 | 実機結果 | 判定 |
| --- | --- | --- |
| Android | Sony SO-41B / Android 13 | 確認済み |
| 画面ロック | `lockscreen.disabled=0`、`password_quality=null`、Device Policy `passwordQuality=0x0`。PIN・パターン・パスワードは検出されなかった。Android再起動後はキーガード表示を観測し、ユーザーが通常解除した | セキュア資格情報なしの読み取り確認。再起動後の無人解除は未成立 |
| USB debugging | `adb_enabled=1`、USB構成`mtp,adb` | 確認済み |
| ADB RSA | 現在および物理USB再接続・Windows再起動・Android再起動後の`adb devices`が`device`状態。`unauthorized`ではない | 各試験でRSA再認証なし |
| `stay_on_while_plugged_in` | `2` | 確認済み。変更なし |
| LINEバッテリー制限 | LINEがDoze whitelistに存在し、明示的なバックグラウンド拒否は検出されなかった | 読み取り確認。設定変更なし |
| ADB/LINE | LINEプロセス稼働、最終状態はADB`device` | 確認済み |

`lockscreen.disabled=0`はキーガード機能が無効ではないことを示すため、PIN等が検出されないことだけから「本体再起動後も無人復旧できる」とは判定しない。本体再起動、ロック設定変更、RSA再認証は行っていない。

### 送信なしの復旧PoC

| 試験 | 実機結果 | 判定 |
| --- | --- | --- |
| ADBサーバー停止→起動 | `adb kill-server` / `start-server`後、再認証プロンプトなしで`device`へ復帰 | PASS（論理再接続） |
| LINE強制終了→ADB起動 | `am force-stop jp.naver.line.android`後、`monkey -p jp.naver.line.android 1`で`MainActivity`前面、ADB`device` | PASS |
| 画面OFF→ADB復帰 | `Asleep`→`Awake`を確認。セキュア資格情報なしの通常スワイプ式キーガードを標準ADBジェスチャーで閉じ、LINEをADB起動して`MainActivity`前面・`mInputRestricted=false` | PASS（今回の端末状態に限る） |

画面OFF試験では人間操作、パスワード入力、ロック突破、スクリーンショット、OCRを使っていない。最終状態は`stay_on_while_plugged_in=2`、ADB`device`、LINE`MainActivity`前面だった。物理USB抜き差しは後続試験でPASSとなった。Android本体再起動後のキーガード解除は人間介入となったため、完全無人復旧はPASSにしていない。

### 現行の無人運用方針

```text
Windowsジョブ開始
  ↓
ADB接続・Android状態確認
  ↓
LINE起動・対象公式アカウント確認
  ↓
Android LINE URLで「最新情報」をtrigger
  ↓
Android uiautomatorで返信を構造取得
  ↓
LINE標準操作で画像保存
  ↓
adb pull
  ↓
Windows RAW保存
```

通常日はAndroidに触れない。人間介入は、LINE初回認証、Android再起動後にセキュアロック解除が必要な場合、RSA再認証、LINE強制ログアウト後の再認証に限定する。ADBやUIAutomatorが失敗した場合は人間操作へフォールバックせず、失敗状態を記録して終了する。Windows版LINEは本番ランタイムから外し、対象確認済みのWindows UIA送信はdebug/fallbackとしてのみ残す。

今回の確認では画面ロック方式・セキュリティ設定・既存Task Schedulerを変更していない。本体再起動後はユーザー解除後にURL target/prefillまで確認できたが、解除前の完全無人復旧は成立しなかった。

## 再起動・再接続耐性の実機確認（2026-09-21）

この試験ではPIA町田へ新しいメッセージを送信していない。復旧確認は、ADB接続、LINE起動、oaMessage URL起動、ヘッダーと入力欄のUI階層確認までとし、送信ボタンは押していない。

| 試験 | ADB復帰 / RSA | LINE起動 | PIA町田・`最新情報` | 人間操作 | 判定 |
| --- | --- | --- | --- | --- | --- |
| 物理USB抜き差し | `device`へ復帰。RSA再認証なし | 成立 | ヘッダー`PIA町田`、入力欄`最新情報`を完全一致確認 | ケーブル抜き差しのみ。画面操作なし | PASS。機械確認は9.1秒、物理抜き差し時間は未計測 |
| Windows再起動 | 自動再起動後はSSH・pingが復帰せず、ユーザーがWindowsを再起動。再起動後はADB`device`、RSA再認証なし | 成立 | ユーザー再起動後にヘッダーとプリフィルを完全一致確認 | Windows再起動に人間介入あり | **human_intervention_required**。ユーザー再起動後の確認処理は20.5秒 |
| Android本体再起動 | 約98秒後に`device`へ復帰。`unauthorized`ではない | ユーザー解除後に成立 | ユーザー解除後にヘッダーとプリフィルを完全一致確認 | `NotificationShade`、`mInputRestricted=true`を観測。自動解除せず、ユーザーが通常解除 | **human_intervention_required** |

Android本体再起動後は`lockscreen.disabled=0`、`password_quality=null`だった。PIN・パターン・パスワードは検出されていないが、キーガード表示と入力制限が残ったため、セキュア認証の有無を推測して自動解除しなかった。ユーザーが通常解除した後、送信なしでLINEを起動し、URL target/prefill確認まで成立した。

この試験の結論は、通常操作と物理USB再接続は無人復旧できるが、Windows再起動は今回の実機状態ではユーザーによるWindows再起動が必要となり、Android本体再起動はキーガード解除に人間介入が必要となった。3試験すべての完全無人復旧PASSとはしない。

## Windows canonical RAW schema実装（2026-09-22）

取得方式の追加探索は行わず、既存の`Android取得 → adb pull → Windows保存`をWindows側の正本保存方式としてコード化した。

- `scripts/raw_storage.py`を追加し、`data/raw/YYYY-MM-DD/<store_id>/`配下の`manifest.json`、`messages.json`、`images/`、`ui/`を管理する。
- PIA町田`text_trigger`を新schemaへ移行した。manifestは`run_id`単位でupsertし、messagesは安定キーでupsertする。
- 画像はWindows側でbyte size/SHA-256を計算し、同一SHA-256なら既存画像を再利用する。
- UI dumpは`ui/<run_id>_reply.xml`等として保存する。
- Windows保存、ハッシュ確認、manifest保存が完了した後だけAndroid一時画像を削除し、削除失敗は`cleanup_warning`として残す。
- A「エムアンドエム溝口」向けに、送信を行わず既存受信メッセージを取得する`passive` adapterを追加した。

ローカルの構文検証と一時ディレクトリによる画像SHA-256重複排除、messages upsert、manifest run_id upsertの検証はPASS。さらにWindows実機の一時配置でAを送信なしで1回実行し、`status=success`、メッセージ1件、UI dump保存、画像0件を確認した。実機のA表示は`rich_card`、LINE表示時刻`20:31`だった。実装後のPIA町田trigger liveは、後述のとおりURL対象確認と送信は成立したが、返信待機が`response_timeout`となったため、新schemaの成功LiveおよびA/B共通schemaのPASSとは判定しない。Task Scheduler本番登録、OCR、AI解析、slot連携、多店舗化は行っていない。

### 画像message occurrence key修正（2026-09-22）

画像ファイルの重複排除とメッセージ発生回の重複判定を分離した。`images/`は同一SHA-256のバイナリを1ファイルへ再利用する一方、`messages.json`の画像message keyには`message_type`、`line_display_time`、`sha256`を含める。同じ画像が異なる時刻に配信された場合は、同一画像ファイルを参照する別message recordとして保持する。

ユニットテスト3件、全スクリプトの構文確認、差分検査はPASS。修正はcommit `60a7b59`としてGitHubへpush済み。

### PIA町田新schema Live試験（2026-09-22）

返信可能とユーザー確認を受け、PIA町田へ新規送信を1回だけ実行した。追加送信は行っていない。

| 項目 | 実機結果 | 判定 |
| --- | --- | --- |
| Windows/ADB | SSH復帰後、Android `HQ615G150D` は`adb devices`で`device` | PASS |
| URL target/prefill | Android LINE URLで`PIA町田`と入力欄`最新情報`を確認してから送信 | PASS |
| trigger | `run_id=154452-a8326c61`、送信時刻は15:45 JST | PASS |
| reply detection / rich_card / image | 90秒待機しても新しい返信なし | **response_timeout** |
| LINE標準保存 / adb pull / Windows `images/` | 返信画像がないため未実行 | 未確認 |
| `messages.json` / `manifest.json` | manifestは失敗runを保存、messagesは空。status=`response_timeout` | 確認済み・Live失敗 |
| Android一時画像cleanup | 送信前後の画像一覧は同じ5件で、新規画像なし。対象画像のcleanupは対象なし | 未適用 |

今回の失敗runを同じmanifest/messagesへ再適用しても、manifest 1件・messages 0件のままであることを確認した。これは失敗runの保存冪等性の確認であり、成功画像を含む完全E2Eの冪等性確認ではない。返信待機の実機結果が失敗だったため、PIA町田の新schema Live、A/B共通RAW schemaのPhase 1 PASS、SHA-256/byte size、画像cleanupは未成立とする。PIA町田への再送信は行わない。
