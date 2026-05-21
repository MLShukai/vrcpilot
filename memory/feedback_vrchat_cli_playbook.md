---
name: vrcpilot CLI で VRChat を操作する playbook
description: SSH/.env 環境で `uv run vrcpilot ...` を組み合わせて VRChat を起動し、メニュー操作・OCR・クリック・移動・後片付けまで行うための運用手順
type: feedback
---

`vrcpilot` の CLI を組み合わせて VRChat を end-to-end で動かすための運用手順。SSH 越しに自分のデスクトップへ VRChat を出して観察・操作する用途を想定する。

**Why:** ユーザーから「CLI で VRChat の UI 操作が可能なレベルまで到達したので、メニューを開いて色々操作するインストラクションを Claude 自身が VRChat を操作するために書いて」と明示依頼あり (2026-05-04)。同日に X11 デスクトップ + Steam 稼働下で起動 → Launch Pad 開閉 → OCR → mouse click → 前進 → terminate まで実機検証済みの手順を、再現できるよう記録したもの。さらに同日の延長セッション (2026-05-04 後半) で featured world への travel、ワールド内移動、各タブの read-only 巡回、`paste` での日本語投入、`R` の Radial Action Menu までを **他人アカウントでの非破壊操作の枠内で** 検証し、得た罠 (§4.1 travel フロー / §5.1 Radial / §8 追補) と禁止事項 (§9 不可逆操作リスト) として反映している。Linux 限定の事実 (Tab で Quick Menu が開かない、`VIRTUAL_ENV=/usr` 警告は無視可など) は実機で見ないと気付かない罠なのでここに保存する価値がある。

**How to apply:**

## 0. 事前条件（SSH 越しに動かすときのチェックリスト）

- **デスクトップセッションが X11**: `XDG_SESSION_TYPE=tty` でも `loginctl ... -p Type` で `Type=x11` ならOK。Wayland native だと window 操作が落ちる
- **Steam が常駐済み**: `pgrep -f steam` で確認。落ちていると `vrcpilot launch` が裏で Steam 起動から始まり 30s タイムアウト超過で `VRChat PID was not observed before timeout` と落ちる
- **`.env` が用意済み**: `.env.example` を `.env` にコピーすれば `DISPLAY=:0` / `XAUTHORITY=$HOME/.Xauthority` が入る

## 1. すべての CLI 呼び出しは `.env` を読み込んだサブシェルで

SSH 直結のシェルは `DISPLAY` を持っていないので、毎コマンド先頭でロードする。

```bash
set -a && . ./.env && set +a && uv run vrcpilot <subcommand>
```

- `set -a` で `.env` 内の `export` が現プロセスに伝播する
- `VIRTUAL_ENV=/usr does not match ... will be ignored` の警告は無害（`uv run` は `.venv` を使うので動く）。報告でも触れない
- `e2e-test` レシピは justfile が DISPLAY フォールバックを持つので不要だが、本 playbook の対象は `uv run vrcpilot ...` を直接叩くワークフロー

## 2. 起動とウォームアップ

```bash
uv run vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60
```

- `--no-vr` で desktop モードを強制（HMD ない環境ではこれを忘れない）
- 起動が確認されると stdout に PID が 1 行出る。終了コード 0 = 起動成功
- launch 直後は **Launch Pad ロゴ + 数字 (01-04) が回る世界読み込み画面**。これは VRChat Hub の演出で、ロード中ではない可能性もある。Esc が効くかが「操作可能になったか」の判定に使える
- 安定するまでの待機目安は **45 秒**（`tests/e2e/_helpers.WARMUP_SECONDS`）。短くするとシェーダコンパイルや Avatar ロードと競合する

## 3. 状態を「見る」ループ

VRChat は黒箱なので、操作前後で必ず screenshot か OCR を取って状態を確認する。

### 3.1 screenshot (生 PNG + window メタデータ)

```bash
uv run vrcpilot screenshot -o /tmp/vrc_<step>.png
```

stdout に YAML が出る。重要なのは `x` / `y` (ウィンドウの絶対位置) と `width` / `height`。これが mouse 座標を window-local から display-absolute へ変換する基準値。

### 3.2 OCR (テキスト + 座標)

`vrcpilot ocr` は **自身でキャプチャしない**（live capture 経路は 2026-05-06 に廃止）。`vrcpilot screenshot` を pipe するか、保存済みの YAML を `--screenshot` で渡す。

```bash
# 一番短い形: インライン base64 を pipe
uv run vrcpilot screenshot | uv run vrcpilot ocr --viz /tmp/vrc_<step>_viz.png > /tmp/vrc_<step>_ocr.yaml

# PNG も残したいとき
uv run vrcpilot screenshot -o /tmp/vrc_<step>.png | uv run vrcpilot ocr --viz /tmp/vrc_<step>_viz.png > /tmp/vrc_<step>_ocr.yaml

# 既存の screenshot YAML を再利用するとき
uv run vrcpilot ocr --screenshot /tmp/vrc_<step>.yaml > /tmp/vrc_<step>_ocr.yaml
```

- 各 word に `pos` (window 内座標) と `display_pos` (絶対デスクトップ座標) の両方が入る
- mouse コマンドへ渡すなら **`display_pos.bbox`** を使う：`[x, y, width, height]` の中央 = `(x + w/2, y + h/2)` が click point
- `--viz` を付けると bbox を重ねた PNG が落ちる。Read ツールで開けば視覚的に妥当性確認できる
- RapidOCR は cp932 関係なくフルで日本語/英語を読める。Launch Pad の "Worlds" / "Avatars" / "Social" / "Safety" / "Home" / "Respawn" などはすべて 99% 信頼度で取れる実績あり

`vrcpilot detect -q <png>` も同じ入力規約。テンプレートマッチ (`TM_CCOEFF_NORMED`) なので Launch Pad のアイコンや特定 UI 要素を OCR より正確に位置特定したいときに使う。

### 3.3 ループの基本形

```bash
# ① 開く前の screenshot
uv run vrcpilot screenshot -o /tmp/vrc_before.png

# ② 操作
uv run vrcpilot keyboard press escape

# ③ 開いた後の screenshot ＋ Read で目視
uv run vrcpilot screenshot -o /tmp/vrc_after.png
```

`Read /tmp/vrc_after.png` で PNG を画像として読めば、Esc で Launch Pad が出たかが目視確認できる。

## 4. メニュー操作 (現行 Launch Pad UI)

VRChat 2026 系の UI では旧 Quick Menu / 旧 Main Menu が **Launch Pad** に統合されている。

| キー                        | 効果                                                              | 備考                                                                        |
| --------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `escape`                    | Launch Pad / 開いている直近のサブダイアログを **1 段だけ** 閉じる | input → サブモーダル → Launch Pad の順で 1 回ずつ。一発全閉じ不可           |
| `r`                         | **Radial Action Menu** を開く                                     | Options / Tools / Expressions / Items / Looks の 5 セグメント。閉じるは Esc |
| `tab`                       | （現行 UI では 効果なし）                                         | 旧 Quick Menu のキーだが、Launch Pad に統合済み。叩いても画面変化しない     |
| `v` / `pageup` / `pagedown` | 視覚変化なし                                                      | 2026 UI ではマップされていないか裏で silent に動く。当てにしない            |

```bash
# 開く
uv run vrcpilot keyboard press escape
# クリック対象を OCR で特定 (screenshot を pipe する)
uv run vrcpilot screenshot | uv run vrcpilot ocr > /tmp/menu.yaml
# 例: "Worlds" タブの display_pos.bbox = [1163, 507, 40, 14] → 中心 (1183, 514)
uv run vrcpilot mouse move 1183 514
uv run vrcpilot mouse click left
# 閉じる
uv run vrcpilot keyboard press escape
```

Launch Pad 上の主なナビゲーション要素 (実機で OCR 取得済): `Launch Pad`, `Explore`, `Avatars`, `Worlds`, `Social`, `Groups`, `Safety`, `Accessories`, `Home`, `Respawn`, `Select`。bottom nav (Home / Worlds / Avatars / Social ...) は `display_pos.y ≈ 642 付近` (1280×720 ウィンドウの場合)。

### 4.1 Worlds タブから別ワールドへ travel する

```bash
# ① Launch Pad → Worlds タブ
uv run vrcpilot keyboard press escape
uv run vrcpilot mouse move 1183 514 && uv run vrcpilot mouse click left

# ② サイドバー or 中央グリッドから featured collection を 1 つ開く
#    例: "VRCat's Variety Box" のラベル中心 (879, 371) を click
uv run vrcpilot mouse move 879 371 && uv run vrcpilot mouse click left

# ③ 中央のグリッドから world card のサムネイルを click
#    text label を直接クリックすると「お気に入り追加」が出てしまう。
#    label の y より 30-40 px 上 = 画像中心を狙う
uv run vrcpilot screenshot | uv run vrcpilot ocr > /tmp/worlds.yaml   # 各 card のラベル位置を取得
uv run vrcpilot mouse move <label_x> <label_y - 30> && uv run vrcpilot mouse click left

# ④ 詳細ペインで Public Instance を確認 → "Join" を click (例: 1117, 404)
uv run vrcpilot mouse move 1117 404 && uv run vrcpilot mouse click left

# ⑤ Loading 画面 (Connecting...) → 入室。ダウンロードは MB/秒 の世界なので
#    "FPS:" や入室後 HUD が見えるまで 30-60s 待つ
```

**0 / N 人の Public Instance を優先** する (誰もいない instance) と、他人を巻き込まずに済む。Friends / Group instance は他人に通知が飛ぶので避ける。

## 5. ワールド内操作

メニューが閉じている状態でキーを送る。`vrcpilot.controls.keyboard.press` のデフォルト `duration=0.1` が VRChat に確実に届く下限なので、**0.0 にしない**（[project_keyboard_press_duration.md](project_keyboard_press_duration.md) 参照）。

| 操作              | コマンド                                   | 補足                                                                                                                        |
| ----------------- | ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| 前進              | `vrcpilot keyboard press w --duration 1.0` | 移動量は duration に比例。0.1 だと一歩、1.0 で 1m 級                                                                        |
| 後退/左右         | `... press s/a/d`                          | 同上                                                                                                                        |
| ジャンプ          | `... press space`                          |                                                                                                                             |
| 走る (押下中のみ) | `... press shift w --duration 1.0`         | 同時押し: `down → sleep → up reversed`                                                                                      |
| 視点回転          | `vrcpilot mouse move <dx> <dy> --rel`      | desktop 視点はマウスキャプチャされており、相対移動で素直に追随。`mouse move 200 0 --rel` で右に振り向けることを実機確認済み |

各 `keyboard press` 呼び出しは独立プロセスのため、キーを「押しっぱなし」で別コマンドを挟むことはできない (uinput 仮想デバイスがプロセス終了で kernel 自動 release される)。複合動作は **1 つの press 呼び出しで `--duration` を伸ばす** か、Python スクリプト側で `down/up` を明示する必要がある。

### 5.1 Radial Action Menu (R キー)

`vrcpilot keyboard press r` で画面中央にリング状の Action Menu が出る。実機で取れたセグメント (位置は 1280×720 desktop ウィンドウ前提):

| セグメント  | display_pos 中心 (例) | 用途        |
| ----------- | --------------------- | ----------- |
| Options     | (1293, 484)           | 設定系      |
| Tools       | (1220, 525)           | カメラ等    |
| Expressions | (1370, 528)           | 表情・emote |
| Items       | (1219, 611)           | 持ち物      |
| Looks       | (1373, 619)           | 見た目変更  |

サブメニューに掘るときは text label をそのままクリックするとリングに戻されることがある。**OCR の text 中心ではなくセグメントのアイコン中心** (リング上の少し外側寄り) を狙うと当たりやすい。閉じるは Esc 一発。

## 6. テキスト入力（非 ASCII を含む）

scancode ベースの keyboard では日本語などが直接打てないので、`paste` を使う。`pyperclip` でクリップボードに乗せて Ctrl+V を送る実装。

```bash
uv run vrcpilot paste "こんにちは、VRChat！"
# あるいは複数行
cat msg.txt | uv run vrcpilot paste
```

検索ボックスやチャットなど、テキスト入力フィールドにフォーカスがある状態で実行する。`mouse click` で入力欄をクリック → `paste` の流れが定石。

実機検証 (2026-05-04): Launch Pad → Social → User Search を選ぶと VRChat 側の virtual keyboard が立ち上がる。その状態で `vrcpilot paste "テスト検索"` を流すと入力欄に日本語がそのまま乗る。**送信ボタン (右側の paper-plane アイコン) を押すと実検索が走る** ので、UI 確認だけしたい場合は paste で止めて Esc で閉じるとよい。

## 7. 終了 (必ずやる)

```bash
uv run vrcpilot terminate
uv run vrcpilot pid; echo "exit=$?"   # exit=1 で何もいないことを確認
```

`terminate` は idempotent (落とすものが無くても exit 0)。実機検証で残骸を残さないため、**操作タスクが成功しても失敗しても最後に必ず terminate** する。`tests/e2e/_helpers.run_scenario` も `try/finally` で同じ規約。

## 8. ハマりどころ早見表

- **Steam が落ちている**: `launch` 開始 30s 後に「VRChat PID was not observed before timeout」。先に Steam を立ち上げる
- **Wayland native セッション**: `vrcpilot focus` / `unfocus` / 入力 guard が `VRChatNotFoundError` 系で落ちる。X11 セッションへ切り替える
- **`VIRTUAL_ENV=/usr` の警告**: 単なる informational。動作に影響なし。報告にも書かない
- **Esc を 1 回押しても画面変化しない**: VRChat がまだ初回ロード中の可能性。45s 待ってから再試行
- **Tab で何も起こらない**: 仕様（Launch Pad 統合済み）。Esc を使う
- **OCR の `pos` をそのまま mouse に渡してしまう**: window 内座標なのでデスクトップが複数モニタや非原点位置だと外す。**必ず `display_pos.bbox`** を使う
- **キープレスが届かない**: `keyboard press --duration 0.05` 以下にしていないか確認。デフォルト 0.1 が確実な下限
- **画面ロック中**: window 操作が安定しない。検証中は lock を外しておく
- **OCR の visibility テキスト揺れ**: confidence 0.9+ でも "Avatar" が "Auatar" になる等のドリフトあり (`step5_ocr.yaml` で実観測)。完全一致でなく `startswith` / `in` でマッチさせるとよい
- **world card label を直接クリックすると「お気に入り追加」ダイアログが出る**: card の label / heart 領域にヒットしている。**サムネイル画像の中心** (ラベルより 30-40px 上) を狙うと world 詳細ペインが開く
- **詳細ペインから travel するには `Join` ボタン**: ラベル "Join" の display_pos 中心を click。Public Instance 0/n で人がいない選択を優先する
- **travel 直後の世界で Respawn を呼ぶと VRChat が落ちることがある**: 2026-05-04 に Grand View 入室直後 (12s 後) に Esc → Respawn (1140, 650) を click したらプロセスが消えた事例 1 件。重要操作はホームで先に試し、travel 後はネット同期と avatar の measure が落ち着く 30s ほど待ってから操作する
- **Esc は 1 段ずつしか閉じない**: input field → 仮想キーボード → サブモーダル → Launch Pad と階層が深いと最大 3-4 回 Esc が必要。間に screenshot を挟んで段階を確認する

## 9. 不可逆 / アカウント状態を変える操作 — 他人アカウント運用時は触らない

`vrcpilot` で他人 (借りた / テスト用) のアカウントを動かすときに **絶対避けるクリック先**。実機検証時に Esc で逃げる癖をつける。

| 操作                       | どこ                                     | 何が起きる                                                                                   |
| -------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Logout**                 | Launch Pad 右上 / Settings               | 再ログイン要 (パスワード/2FA)。ユーザーへ操作権限を返す合図                                  |
| **Make Home**              | World 詳細ペインの button                | home world が変わる。ユーザーの初期スポーン挙動が変わってしまう                              |
| **Block & Report**         | プロフィール / 右パネルの "Block&Report" | 他人にアクションが飛ぶ。**取り消し UI が分かりづらい**                                       |
| **Friend / Unfriend / DM** | Social タブ内のフレンド名                | 第三者に通知が飛ぶ。ボタンが密集していて誤爆しやすいので **Social はサイドバーまでで止める** |
| **Avatar 切替**            | Avatars タブの avatar カード             | 見た目が変わる。clone 元等で問題になることもあるので clone してない avatar はクリックしない  |
| **Safety Shield Level**    | Safety モーダル (None/Low/Medium/High)   | trust 設定で他人の表示可否が変わる。モーダルが出たら選択肢に触らず Esc                       |
| **VRC+ / Shop 購入**       | Launch Pad 右パネル / VRC+ タブ          | 課金。確認ダイアログでも誤クリック注意                                                       |
| **Quit** (Settings)        | Launch Pad 上部メニュー                  | VRChat を終了する。`vrcpilot terminate` で代替し、UI からは触らない                          |

**Safe な操作** (検証で確認した non-destructive な範囲):

- Launch Pad / 各タブの open/close
- Worlds / Avatars / Social / Groups タブのサイドバー巡回 (中身を見るだけ)
- Public Instance への travel (0 人 instance を選べば誰にも見られない)
- ワールド内の WASD / Space / Shift+W / mouse rel 視点回転
- `paste` で入力欄に文字列を乗せる (送信ボタンは押さない)
- R で Radial Menu を開いて閉じる (サブメニューを 1 段見る)
- Respawn (落下事故等の状態リセット — ただし上記事例の通り travel 直後は注意)

迷ったら `vrcpilot screenshot` を 1 枚撮って画面を確認する。**ボタンが何かラベルなしで分からないときはクリックしない**。

## 10. 1 セッション分のミニマルな実行例

```bash
# .env を取り込んだサブシェルで全部やる
(set -a && . ./.env && set +a && \
  uv run vrcpilot terminate && \
  uv run vrcpilot launch --no-vr --screen-width 1280 --screen-height 720 --wait-timeout 60 && \
  sleep 45 && \
  uv run vrcpilot keyboard press escape && \
  uv run vrcpilot screenshot -o /tmp/vrc_menu.png \
    | uv run vrcpilot ocr --viz /tmp/vrc_menu_viz.png > /tmp/vrc_menu.yaml && \
  uv run vrcpilot keyboard press escape && \
  uv run vrcpilot terminate)
```

これで「起動 → メニュー開く → 状態取得 → 閉じる → 終了」が再現できる。`screenshot -o` で残した `/tmp/vrc_menu.png`、`ocr --viz` で残した `/tmp/vrc_menu_viz.png`、stdout を流し込んだ `/tmp/vrc_menu.yaml` の 3 つを Read で読めば次の操作（クリック対象の選定など）が組める。
