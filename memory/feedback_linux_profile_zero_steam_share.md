---
name: linux-profile-zero-steam-share
description: Linux で `vrcpilot.launch(profile=0)` は Steam compatdata の pfx を WINEPREFIX として共有する。Windows の profile=0 挙動 (Steam 経由と同一アカウント) と Linux を揃えるための設計
metadata:
  type: feedback
---

Linux で `vrcpilot.launch(profile=0)` (direct-spawn) を呼ぶと、WINEPREFIX は `<library>/steamapps/compatdata/438100/pfx` を **自動マッピング**する。Steam 経由起動 (`via_steam=True`) と同一 wineprefix を共有するため、ログイン状態・SaveData・cookie が direct-spawn と Steam 経路で完全に揃う。compatdata pfx が未初期化なら fail-fast で `VRChatSteamCompatdataNotFoundError` を送出する (silent fallback で別 prefix を作らない)。

**`profile=0` は `launch()` / CLI の新デフォルト** (2026-05-25 変更)。無引数の `vrcpilot launch` / `vrcpilot.launch()` がそのまま「Steam アカウントで起動」になる。`via_steam=True` と `profile=0` は等価セマンティクスなので `validate_launch_args` も両者の同時指定を許容する (`profile>0` だけが `via_steam` と排他)。明示的に umu のデフォルト prefix を使いたい稀な場合は `profile=None` を渡す。

**Why:**

- 2026-05-25 ユーザー要求: 「`vrcpilot launch --profile 0` で Steam アカウントをそのまま使いたい (毎回ログインし直したくない)」。direct-spawn は本来 umu-launcher のデフォルト prefix を作るので、Steam 経由とは別アカウント状態になっていた
- Windows との挙動差分: VRChat 本体は `--profile=0` を「デフォルトスロット = Steam 経由起動と同じ場所」として扱う。Windows ではそもそも wineprefix がないので、SaveData が `%APPDATA%\..\LocalLow\VRChat\VRChat\` 1 箇所に集約され、Steam 経由 / direct-spawn 区別なく同一データになる。Linux でも同じ semantics を満たすには、`profile=0` のとき Steam-managed compatdata を共有する必要があった
- silent fallback (pfx 無ければ新 prefix 作る) を避けた理由: ユーザーが `--profile 0` を指定した時点で「Steam と同じアカウントを使う」という強い意図がある。pfx が無いのは「Steam で VRChat を一度も起動していない」という前提違反なので、fresh prefix を作ってログイン画面を出すよりも明示エラーで「`--via-steam` を 1 回走らせて pfx を bootstrap してほしい」と伝える方が正しい

**How to apply:**

- `--profile 0` は Steam-shared。`--profile 1, 2, ...` は per-profile isolated (vrcpilot-managed `$XDG_DATA_HOME/vrcpilot/profiles/<N>/wineprefix` を新規作成)。これは \[\[linux-direct-spawn-no-gameid\]\] の「複数アカウント運用」と整合
- `--wineprefix=<path>` を明示すると `profile` 値より優先される (override の優先順位は `wineprefix` > `profile==0` > `profile>=1` > `profile==None`)。「Steam compatdata だが別 library」を使う等の edge case はこれで対応
- e2e 検証は VRChat 起動後の screenshot で判別: Home world が読み込まれていれば Steam アカウントが効いている (`--profile 0` 成功)、"Welcome to the world of VRCHAT / Login with VRChat / Steam / Discord" が出ていればログイン画面 = 独立 prefix。実機検証手順は \[\[memory/feedback_vrchat_cli_playbook.md\]\] を踏襲
- 関連テスト: `tests/vrcpilot/process/test_linux.py::TestSteamCompatdataPfx` (path 構築)、`tests/vrcpilot/process/test_linux.py::TestResolveDirectSpawnWineprefix` (4 段階優先順位)。動作変更時は両方を更新
- pfx 未初期化エラーが出たユーザーへの案内は 2 つ: (1) `vrcpilot launch --via-steam` を 1 回走らせて pfx を bootstrap (2) `--wineprefix=<path>` で既存 prefix を渡す。fail-fast メッセージにこの案内が含まれている (`process/linux.py::resolve_direct_spawn_wineprefix`)

関連: \[\[linux-direct-spawn-no-gameid\]\] / \[\[memory/feedback_vrchat_cli_playbook.md\]\]
