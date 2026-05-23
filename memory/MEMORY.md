# プロジェクトメモリ

`vrcpilot` プロジェクト固有のメモリインデックス。詳細は各ファイルへ。

各セッション開始時、または規約が関係するタスク着手前にここを確認する。新しい規約・知見が見つかったらファイルを足し、ここから 1 行リンクを張る。

## feedback（規約・ガイドライン）

- [private モジュール規約](feedback_private_module_convention.md) — `_` prefix はテスト無しの真 private 限定。テストするなら prefix を外す
- [tests ミラーレイアウト](feedback_test_layout_mirror.md) — `tests/` は `src/vrcpilot/` を 1 対 1 でミラーリングする
- [テスト戦略 4 区分](feedback_test_strategy.md) — unit / integration-with-fakes / integration-real / e2e。skip はファイル先頭で
- [lint ツーリング集約](feedback_lint_tooling.md) — ruff/docformatter 等は pre-commit に集約。指示・報告では「`just run`」「pre-commit 全 hook」と書く
- [実装は e2e まで Claude が回す](feedback_e2e_run.md) — `just run` だけでなく `just e2e-test <NAME>` + スクショ確認まで完了条件に含める
- [計画ドキュメントは日本語](feedback_planning_doc_language.md) — plan ファイル・設計提示は日本語で書く。コード/識別子/コマンドは英語のまま
- [vrcpilot CLI で VRChat を操作する playbook](feedback_vrchat_cli_playbook.md) — SSH/.env 環境で起動 → メニュー → OCR → click → 移動 → terminate の実機検証済み手順
- [Linux direct-spawn は GAMEID を渡さない](feedback_linux_direct_spawn_proton.md) — GAMEID=438100 を umu-run に渡すと ProtonFixes が壊れた global defaults を当てて wine 即死。`--app-id` は via_steam 専用
- [許可済みコマンドを優先する](feedback_use_allowed_commands.md) — `.claude/settings.json` の allow に載った形で Bash/Read を組み立てる。確認プロンプトで自走が止まるのを防ぐ

## project（実装上の固有事情）

- [keyboard.press の duration デフォルト 0.1](project_keyboard_press_duration.md) — VRChat/Unity が短すぎる keypress を取りこぼすので 0.0 に戻さない
- [pipewire null-sink module 廃止問題](project_pipewire_null_sink_module_removed.md) — `mic enable` が書き出す古い conf で PipeWire 1.0+ が起動不能になる。退避 + reset-failed で復旧、テンプレ自体は要修正

## reference（外部ツール・パス）

- [gh CLI は絶対パスで呼ぶ](reference_gh_executable_path.md) — `"/c/Program Files/GitHub CLI/gh.exe"` で呼ぶ。PATH には通っていない
