---
name: linux-direct-spawn-no-gameid
description: Linux で `vrcpilot.launch()` の direct-spawn (`umu-run launch.exe`) は **GAMEID env を渡さない**。GAMEID=438100 を渡すと umu-launcher の ProtonFixes が壊れた global defaults を当てて wine が死ぬ
metadata:
  type: feedback
---

`vrcpilot.launch()` の 0.3.0 デフォルト経路は Linux では `umu-run /path/to/VRChat/launch.exe`。**`GAMEID` env を渡してはいけない**。

**Why:** 2026-05-23 の実機 e2e で発覚。初期実装は umu-run に `GAMEID=438100` (VRChat の Steam app id) を渡していたが、これだと:

1. umu-launcher の ProtonFixes が `438100` を CSV で検索 → 該当なし (VRChat の正規 fix は未登録)
2. "global defaults for UNKNOWN (438100)" を当てる
3. その global defaults が `coremessaging.dll.DllGetActivationFactory` を使う設定を含む
4. UMU-Proton-latest にはこの関数の実装が無い → `wine: ... unimplemented function coremessaging.dll.DllGetActivationFactory, aborting`
5. wine プロセスが即死 → warmup 中に VRChat.exe が消えて `find_pids()` が空になる

**GAMEID を渡さなければ** umu は ProtonFixes の global defaults を当てず、素の wine prefix で起動する。これで `umu-run launch.exe --no-vr` 相当の安定起動になる (実機検証: ユーザーが手で `umu-run launch.exe --no-vr` を実行すると動くと報告 → vrcpilot 経由でも GAMEID を外した瞬間に動く)。

修正: `src/vrcpilot/process/launch.py` の Linux direct-spawn 分岐から `env_overrides["GAMEID"] = str(app_id)` を削除。コメントで上記の経緯を残してある。`app_id` 引数は `via_steam=True` の `steam.exe -applaunch <app_id>` 経路でのみ意味を持つ (docstring 修正済)。

**How to apply:**

- Linux で direct-spawn を試すとき、もし WINEPREFIX を明示せず umu-launcher の素の prefix で起動する設計を続けるなら、**GAMEID は引き続き付けない**。今後 `--app-id` 系の引数を追加するときも direct-spawn では env に乗せない
- ProtonFixes upstream に VRChat (438100) の正規 fix エントリが追加されたら、GAMEID 付与を復活させる価値があるかもしれない。ただし最初に「GAMEID=438100 を渡しても DLL エラーで死なないこと」を実機で再確認すること
- `tests/vrcpilot/process/test_launch.py::TestLaunchDirectSpawnLinux::test_does_not_set_gameid_env` がこの仕様をロックインしている。将来「GAMEID をなぜ付けてないんだっけ?」となった人はこのテストとコメントを読む
- e2e `tests/e2e/launch_terminate.py` / `cli_launch_terminate.py` も GAMEID 修正後に PASS する (2026-05-23 実機確認)

## 仮想 prefix の話 (補足)

GAMEID を渡さない結果、umu-launcher は `~/.local/share/umu/...` 配下に独自の wine prefix を初期化する。Steam の `compatdata/438100/pfx` とは別なので、VRChat のデータ (Saved/, AppData/LocalLow/VRChat) は **direct-spawn 経路と via_steam=True 経路で別の場所に作られる**。これは複数アカウント運用 (`--profile N`) と整合的な設計で、同一アカウントを direct-spawn と Steam で行き来したいユーザーは `--wineprefix /home/<user>/.local/share/Steam/steamapps/compatdata/438100/pfx` で明示する必要がある。

関連: \[\[memory/feedback_vrchat_cli_playbook.md\]\]
