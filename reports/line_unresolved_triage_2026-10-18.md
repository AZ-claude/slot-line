# LINE取得方式未確定の確認順（2026-10-18）

登録 220 件／方式未確定 112 件。未確定の全店は受動取得のみ。

|状況|件数|次の対応|
|---|---:|---|
|`menu_visual_review_required`|0|メニュー表示を再撮影|
|`insufficient_evidence`|0|初回の表示・証拠を再確認|
|`action_executed_result_unconfirmed`|12|操作後の返信・遷移を再確認（再押下しない）|
|`latest_like_label_not_executed`|1|曖昧なボタンを判断|
|`liff_consent_required`|4|LIFF認証の扱いを判断|
|`latest_action_external_app`|1|外部アプリ遷移の扱いを判断|
|`menu_reviewed_no_latest_label`|94|明確な最新情報ボタンなし。受動取得を継続し追加証拠を確認|

2026-10-18にバンバンポラリスを方式A、BIGパンドラ井土ヶ谷店本館を方式Bに確定。ドキわくランド北山田店・マルハン小田原店・パールショップともえ淵野辺店はメニューを再確認したが、取得方式は保留。

端末操作は21:30〜23:30 JSTを避ける。既に押した店舗のボタンは再度押さない。LIFF認証は許可しない。根拠がない場合は未確定を維持する。

## menu_visual_review_required

0件：メニュー表示を再撮影。

|店舗|ホールID|現状の証拠|
|---|---|---|

## insufficient_evidence

0件：初回の表示・証拠を再確認。

|店舗|ホールID|現状の証拠|
|---|---|---|

## action_executed_result_unconfirmed

12件：操作後の返信・遷移を再確認（再押下しない）。

|店舗|ホールID|現状の証拠|
|---|---|---|
|中山UNO|`nakayama-uno`|No visible reply or navigation within 12 seconds of the single tap.|
|キコーナ伊勢佐木店|`kik-na-isezaki-ten`|No visible reply or navigation within 12 seconds of the single tap. 2026-10-18 00:40 JSTに押下なしで再撮影。以前の最新情報ボタン押下への返信や遷移は確認できず、方式未確定を維持。|
|キコーナ秦野店|`hall-8c575c49425feb75`|No visible reply or navigation within 12 seconds of the single tap. 2026-10-18 00:41 JSTに押下なしで再撮影。特設HPボタン押下への返信や遷移は確認できず、方式未確定を維持。|
|ＺＡＰ舟倉店|`hall-c8433dcaf6de3aa4`|The '最新情報はこちら' banner is a heading; tapping it did nothing within 12 seconds.|
|キコーナ戸塚店|`kik-na-totsuka-ten`|The 最新情報 block is a new-machine banner; tapping it at 16:02 JST produced no reply or navigation.|
|スクランブル田谷店|`sukuramburu-taya-ten`|Single tap at ~15:56 JST (guards passed; the post-tap capture timed out). A re-snapshot at 16:07 without tapping shows no new store message (latest 20:00 the previous day); an exte|
|アビバANNEX ＆ SQUARE|`hall-f39976506d3719e5`|The chat showed a loading spinner after the tap and the re-check could not reopen the chat; result not yet observed. The welcome message announces a LINE account change (new accoun|
|アビバ三春町店|`abiba-miharu-machi-ten`|Owner approved tapping it (2026-10-09). The tile only switched the menu image to 戻る plus a list of store-manager X accounts (横須賀アビバグループ 店長X); no latest-information content appeared|
|ピーアーク新城マックスパチンコ|`p-ku-shinj-makkusu-pachinko`|The tile sent the text 「最新情報」 and the store answered with a card carousel (rendered as blank white cards even in the re-check capture, so the content is not readable). Owner to sen|
|マルハン茅ヶ崎店|`maruhan-chigasaki-ten`|Tapped the schedule banner once (useful-looking tile); nothing opened and no message arrived.|
|パサージュ寒川店|`hall-04cdbadc9a018193`|Tapped the 取材 banner once. The tile sent the text 「サンスポ取材10.10全店合同取材」 but no store reply appeared within two minutes (re-check capture). A later re-check may show a reply. 2026-10-|
|HAPPY G・FUJISAWA|`happy-g-fujisawa`|The store replied with a card carousel (「➡へスライド！」); the cards stayed blank white in the capture and in a re-check, so the content is not readable from the phone.|

## latest_like_label_not_executed

1件：曖昧なボタンを判断。

|店舗|ホールID|現状の証拠|
|---|---|---|
|シーサイドプラザ|`sh-saido-puraza`|Daily-updated blog tile is ambiguous; no tap performed.|

## liff_consent_required

4件：LIFF認証の扱いを判断。

|店舗|ホールID|現状の証拠|
|---|---|---|
|グランドホール港南店|`gurando-h-ru-k-nan-ten`|A LINE LIFF consent screen (認証, provider グランドホール港南店) opened; it was not approved and was closed.|
|吉兆東名川崎店|`kitch-t-mei-kawasaki-ten`|Tapped once on 2026-10-09 00:29 JST (chat opened by the owner after the talk-list lookup failed on 10-04 and 10-09). A LINE LIFF consent screen (認証, provider 株式会社キャスメディア / 吉兆東名川崎店)|
|キコーナ仲町台店|`hall-e3ad828521fb24fc`|A LINE LIFF consent screen (認証, provider アンダーツリー株式会社2) opened; it was not approved and was closed.|
|キコーナ溝の口店|`hall-86d2c28146564510`|A LINE LIFF consent screen (認証, provider アンダーツリー株式会社) opened; it was not approved and was closed.|

## latest_action_external_app

1件：外部アプリ遷移の扱いを判断。

|店舗|ホールID|現状の証拠|
|---|---|---|
|ZAP PRESTIGE|`zap-prestige`|Opened the X app (com.twitter.android) on @ZAP_prestige777; not a web or LINE source.|

## menu_reviewed_no_latest_label

94件：明確な最新情報ボタンなし。受動取得を継続し追加証拠を確認。

|店舗|ホールID|現状の証拠|
|---|---|---|
|123横浜西口店|`123-yokohama-nishiguchi-ten`||
|ドキわくランド長後駅前店|`doki-waku-rando-ch-go-ekimae-ten`||
|キコーナ茅ヶ崎店|`kik-na-chigasaki-ten`||
|キコーナ白楽店|`kik-na-bakuro-ten`||
|ビッグパンドラ井土ヶ谷店新館|`biggu-pandora-ido-ke-tani-ten-shinkan`||
|グランドホール小田原店|`gurando-h-ru-odawara-ten`|Earlier latest-information candidate '☆最新情報はこちら☆' is the rich-menu bar title (menu open/close toggle), not a menu action; withdrawn.|
|トワーズ相模原店|`tow-zu-sagamihara-ten`||
|ジャパンニューアルファ倉見店|`japan-ny-arufa-kurami-ten`||
|ドキわくランド井土ヶ谷店|`doki-waku-rando-ido-ke-tani-ten`||
|ガイアネクスト海老名駅前店|`gaianekusuto-ebina-ekimae-ten`||
|パールショップともえ淵野辺店|`p-ru-shoppu-tomo-e-fuchinobe-ten`|2026-10-18再撮影でメニューありを確認。「最新情報はこちら PUSH P-WORLD」は外部P-WORLDへの案内で、LINE返信を取るボタンではない。押下せず、受動取得を継続。|
|ARROW平塚店|`arrow-hiratsuka-ten`||
|新！ガーデン戸塚|`new-garden-totsuka`|'公式X情報 19時更新' points to X, not a LINE latest-information action.|
|南武線尻手駅前店|`nambusen-shitte-ekimae-ten`||
|ギンザホール707|`ginzah-ru-707`||
|グリーン|`gur-n`||
|東横フェスタ3|`higashiyoko-fesuta-3`||
|ジャラン平塚店|`ja-ran-hiratsuka-ten`||
|マルハン橋本台店|`maruhan-hashimotodai-ten`||
|マルハン厚木店|`maruhan-atsugi-ten`||
|MONOS川崎|`monos-kawasaki`||
|デイズ新杉田店|`deizu-shinsugita-ten`||
|ジアス港南台|`jiasu-k-nandai`|Banner only points to the tiles below; no dedicated latest-information tile.|
|ガイア和田町店|`gaia-wada-machi-ten`||
|ニューリッチランド|`ny-ritchirando`|Welcome message advertises machine-data keyword search (台番号/機種名).|
|メガフェイス1180座間|`mega-feisu-1180-zama`|Onboarded after the owner confirmed on 2026-09-27 that LINE profile MEGAFACE1180座間 is this hall.|
|ジアス大船|`jiasu-bune`|Menu bar title '最新情報はコチラ' is the open/close toggle, not a tile.|
|楽園上永谷店|`rakuen-kaminagaya-ten`||
|ノア上永谷店|`hall-79ab16be0b4394fd`||
|横須賀・馬堀マリーン|`yokosuka-mabori-mar-n`||
|デルパラ大和店|`hall-c6b84e1256adfaf9`||
|横浜マリーン|`yokohama-mar-n`||
|グランドホール長後店|`gurando-h-ru-ch-go-ten`||
|クラブニューヨーク反町|`kurabu-ny-y-ku-tammachi`||
|PIA大船1店|`hall-5f23ce7bab3bec39`||
|SS ZAP京急久里浜店|`hall-c59a3855044451cd`||
|やすだ大和店|`yasu-da-yamato-ten`||
|ドキわくランド北山田店|`doki-waku-rando-kitayamata-ten`|2026-10-18再撮影でリッチメニュー表示を確認。新台入替告知、フロアマップ、台データ、店舗Xのみ。明確な最新情報取得ボタンはないため受動取得を継続。|
|ヒノマル新丸子西口 スロット館|`hall-9f780a1b45b5d558`|Onboarded after owner confirmation of profile name ヒノマル新丸子.|
|キングＥＸ|`hall-5abd6f0e82dc6445`|'最新情報' tile points to a LINE OpenChat, not the official account; not executed.|
|マルハン小田原店|`maruhan-odawara-ten`|2026-10-18再撮影で折りたたまれたメニューを確認し、開閉バーだけを開いて内容を目視。最新情報取得ボタンは見当たらず、受動取得を継続。|
|トワーズ麻溝台店|`tow-zu-asamizodai-ten`||
|ガイア川崎スロット専門店|`gaia-kawasaki-surotto-semmon-ten`||
|ダイナム相模原店|`dainamu-sagamihara-ten`|Switched to the new account @320qwyfb (owner approved 2026-09-29). The old account @fxl9564y stays friended with the same display name, which the talk-list collector cannot tell ap|
|ドキわくランド橋本店|`doki-waku-rando-ky-honten`||
|ドルフィン|`hall-31aaf6de4df9babe`||
|ジャパンニューアルファ 鶴ヶ峰店|`hall-3db00880aaca73a8`||
|キコーナ鶴見中央店|`kik-na-tsurumi-chuo-ten`||
|Ｄ’station上永谷店|`hall-53654a43dbfae2a3`|Onboarded after the owner confirmed profile D'station上永谷店 is this hall.|
|PIA川崎新川通り店|`hall-b8c21b0b4bda81d9`||
|PREST 弥生台店|`hall-43832bf3d34f5004`|「最新情報はこちら」はX公式に遷移する行のため押下しない。owner確認済み。|
|ヒノマル向ヶ丘遊園店|`hinomaru-muk-gaoka-y-en-ten`||
|コンパル橋本|`komparu-hashimoto`||
|トワーズ厚木店|`tow-zu-atsugi-ten`||
|トワーズ大和深見店1120|`tow-zu-yamato-fukami-ten-1120`|owner確認で最新情報ボタンなしとして追加。|
|PASSAGE 弘明寺駅前店|`hall-75c652995806ad35`|owner確認で最新情報ボタンなしとして追加。未認証アカウント。|
|グランド アクア|`hall-6d3dcf249959a4cd`||
|ノア 溝口店|`hall-70484ca736a3a65e`|The welcome message says the buttons show 最新情報, but no button is labelled as such; not tapped.|
|サンラッキー 中央林間店|`hall-50b3144563516470`||
|パーラーフィオーレたまプラーザ|`p-r-fi-re-tama-pur-za`||
|クリエ湘南台店|`kurie-sh-nandai-ten`||
|ピーアーク相模原|`p-ku-sagamihara`||
|パチンコＦＵＪＩ伊勢原店|`hall-96bfe9c243f3186d`|Owner confirmed LINE name FUJI伊勢原店 = パチンコＦＵＪＩ伊勢原店 (2026-10-01).|
|Super Slot Club Z|`hall-e7472263f7fa35af`|Owner confirmed LINE name スーパースロットクラブZ = Super Slot Club Z (2026-10-01).|
|パラッツォ秦野渋沢店|`parattso-hadano-shibusawa-ten`||
|トワーズ大和店|`tow-zu-yamato-ten`||
|吉兆横浜西寺尾店|`kitch-yokohama-nishiterao-ten`||
|PASSAGE３横浜泉店|`hall-08678a468fa62e97`|Owner confirmed LINE name パサージュ3 横浜泉店 = PASSAGE３横浜泉店 (2026-10-02).|
|アビバ 三浦海岸店|`hall-d8be5720a9636cd2`||
|キコーナ平塚店|`hall-d3dce3cd9b305dcf`||
|キコーナ伊勢原店|`hall-c5e95b44e86be1d3`||
|ドラゴン小田急相模原店|`doragon-odaky-sagamihara-ten`||
|シーザースパレス|`sh-z-suparesu`||
|キコーナ相武台店|`hall-ad2388ecfad0dc62`||
|ともえセン南駅すぐよこ店|`tomoe-sen-minami-eki-sugu-yo-ko-ten`|The only latest-like tile is labelled 'P-WORLD 最新情報' (P-WORLD link); not tapped.|
|キコーナ海老名店|`kik-na-ebina-ten`|No latest-information tile; the 'every day updated' tile is the store X account.|
|グランドオータ厚木店|`gurando-ta-atsugi-ten`|No latest-information tile.|
|ドキわくランド大和駅前店|`doki-waku-rando-yamato-ekimae-ten`|No latest-information tile; the banner is an ambassador promotion and was not tapped.|
|甲子園２|`hall-1003b8d33c81c863`|No latest-information tile.|
|ＰＲＥＳＴ三ツ境店|`hall-bf56f04e72466730`|No latest-information tile. The welcome message asks 「あなたの得意機種は？」 with quick-reply buttons (パチンコ/パチスロ/両方); they send a message, so they were not tapped.|
|アサヒ2鹿島田店|`asahi-2-shika-shimada-ten`|No latest-information tile; the only 最新情報 label is on the X tile.|
|ベルシティザシティ川崎店|`hall-f931697dc1527592`|No latest-information tile.|
|サンパチンコ|`sampachinko`|No latest-information tile.|
|セントラル|`hall-af3450c4fdeb6190`|No latest-information tile. The スケジュール tile (TimeTree) looked useful but was not tapped: opening the chat by name failed twice (chat_header_mismatch), so it is left for a later pas|
|チャレンジャーB館|`charenj-b-kan`|No latest-information tile. The chat is named チャレンジャーA館・B館 and serves both チャレンジャーA館 and チャレンジャーB館 (owner confirmed 2026-10-11).|
|鶴見UNO|`tsurumi-uno`|No clearly labeled latest-information tile in the captured menu.|
|glow AMUSEMENTHALL|`glow-amusementhall`|No clearly labeled latest-information tile in the captured menu.|
|チャンピオン田名店|`champion-tana-ten`|No clearly labeled latest-information tile in the captured menu.|
|プラザ上大岡アンドミラージュ|`puraza-kami-oka-ando-mir-ju`|No clearly labeled latest-information tile in the captured menu.|
|金時鶴見店|`kintoki-tsurumi-ten`|No clearly labeled latest-information tile in the captured menu.|
|MONOS 寒川南館|`hall-1ff439bb2e6000c4`|No clearly labeled latest-information tile in the captured menu.|
|マルハンメガシティ横浜町田|`maruhammegashiti-yokohama-machida`|No clearly labeled latest-information tile in the captured menu.|
|ニラク海老名本郷店|`hall-fa602d8bd96d0ae2`|No clearly labeled latest-information tile in the captured menu.|
|SLOT ACT|`slot-act`|No clearly labeled latest-information tile in the captured menu.|
