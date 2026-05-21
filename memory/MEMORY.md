# プロジェクトメモリ

`vrcpilot` プロジェクト固有のメモリインデックス。詳細は各ファイルへ。

各セッション開始時、または規約が関係するタスク着手前にここを確認する。新しい規約・知見が見つかったらファイルを足し、ここから 1 行リンクを張る。

## feedback（規約・ガイドライン）

- [private モジュール規約](feedback_private_module_convention.md) — `_` prefix はテスト無しの真 private 限定。テストするなら prefix を外す
- [tests ミラーレイアウト](feedback_test_layout_mirror.md) — `tests/` は `src/vrcpilot/` を 1 対 1 でミラーリングする
- [テスト戦略 4 区分](feedback_test_strategy.md) — unit / integration-with-fakes / integration-real / e2e。skip はファイル先頭で
- [lint ツーリング集約](feedback_lint_tooling.md) — ruff/docformatter 等は pre-commit に集約。指示・報告では「`just run`」「pre-commit 全 hook」と書く
- [e2e は Claude が実行](feedback_e2e_run.md) — `tests/e2e/` は人手作業に残さず Claude 自身が `just e2e-test` で実機検証する
- [計画ドキュメントは日本語](feedback_planning_doc_language.md) — plan ファイル・設計提示は日本語で書く。コード/識別子/コマンドは英語のまま
- [vrcpilot CLI で VRChat を操作する playbook](feedback_vrchat_cli_playbook.md) — SSH/.env 環境で起動 → メニュー → OCR → click → 移動 → terminate の実機検証済み手順

## project（実装上の固有事情）

- [keyboard.press の duration デフォルト 0.1](project_keyboard_press_duration.md) — VRChat/Unity が短すぎる keypress を取りこぼすので 0.0 に戻さない
