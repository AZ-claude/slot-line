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

`DESIGN.md` は `origin/main` から取得し、614行を全文確認済み。以後は同設計のPhase 0/Phase 1の境界と、YAGNI方針を正とする。

## 確認結果

| 項目 | 結果 | 根拠・備考 |
| --- | --- | --- |
| `DESIGN.md` 全文確認 | 確認済み | `origin/main` の `04086c4` にある614行を確認した。 |
| Windows版LINEのインストール | 確認済み | `winget list --name LINE` でMicrosoft Store版 `8.3.0.3189` を確認し、ログイン済みの `LINE.exe` 稼働も確認。 |
| Chrome版ではなくデスクトップ版 | 確認済み | WindowsのLINEデスクトップアプリ登録とMicrosoft Store ID `XPFCC4CD725961` を確認。 |
| 専用LINEアカウントのPCログイン | 確認済み | ユーザーがログインを完了し、Windows版LINEの通常トーク一覧を確認。LINEプロセスも稼働中。 |
| 自動ログイン設定 | 未確認 | Windows版LINEのログイン画面を確認していない。 |
| Windows再起動後の復帰 | 未確認 | 再起動試験を行っていない。 |
| LINEプロセス再起動後の復帰 | 未確認 | プロセス試験を行っていない。 |
| ログアウト状態の検知 | 未確認 | 状態表示・プロセス・通知の観測方法を試していない。 |
| Android版LINEのメイン端末利用 | 部分確認 | ユーザーがA/Bを登録済み。ADB確認時は端末がロック画面で、トーク一覧・ログイン状態を画面確認できていない。 |
| USB debugging / ADB | 確認済み（現時点） | WindowsのADB 37.0.1でSO-41Bが状態 `device` として認識されている。再接続・再起動耐性は未確認。 |
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
