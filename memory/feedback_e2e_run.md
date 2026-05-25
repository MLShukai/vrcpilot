---
name: 実装は e2e まで Claude が回す
description: 実装タスクはユニット/型/lint だけでなく e2e (`just e2e-test`) まで Claude 自身が実行・検証して初めて完了とみなす
metadata:
  type: feedback
---

`tests/e2e/` 配下の e2e シナリオは「実機 VRChat が必要だから人手検証」と扱わず、Claude セッション内で実行して動作確認・スクリーンショット確認まで行う。さらに、**実装タスクの完了条件として `just run` 通過だけでなく対応する e2e シナリオの実行 (`just e2e-test <NAME>`) まで Claude 側で回す**。

**Why:**

- 2026-05-02: 「e2e を人手作業とせずやるよう記憶してください」とユーザー指示あり
- 2026-05-21: 「実装するときは基本的に e2e テストまで実施することを記憶したい」と再度明示。`just run` (format + unit/integration + pyright) だけ通して「あとは人手で」と引き渡すと、結局ユーザーが手動で VRChat を立ち上げて確認することになり自走の意味が薄れる
- Linux 環境では SSH 越しでもデスクトップセッション (X11/XWayland) があれば `just e2e-test <NAME>` を実行可能で、`_helpers.save_monitor_screenshot` の出力 PNG を `Read` ツールで開けば視覚的確認まで Claude 側で完結する

**How to apply:**

- 機能を実装したら **対応する e2e シナリオを書く / 既存シナリオを更新する** ことを既定にする。明示的に不要と判断できる場合 (純粋ロジックのみで実機影響なし、共有ヘルパの軽微な改修など) のみスキップしてよい
- 実装ステップで e2e シナリオを書いたら、続けて `just e2e-test <NAME>` を実行する
- SSH 越しでも `just e2e-test <NAME>` だけで OK。justfile が `DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" uv run python ...` の形でデフォルトフォールバックを持っているため、env を自分で前置する必要はない
- 出力 `_e2e_artifacts/<scenario>/<YYYYMMDD_HHMMSS>/<label>.png` を `Read` ツールで開いて期待通りか検証する
- `PASS:` で終わっていてもスクリーンショット内容に異常があれば failure 扱いで再修正する
- 実機都合 (Steam 起動忘れ、Wayland native セッション、uinput 権限不足など) で失敗したらユーザーに環境を依頼するが、それは「人手検証」ではなく「環境セットアップ依頼」として明確に区別する
- エージェントを起動するときも「e2e シナリオの実行は本タスクの責任外」と書かない。実装エージェントには「書いて `just run` を pass させる」までを依頼し、`just e2e-test` は親 (Claude 本体) が実行する分担にする
- 完了報告のテンプレ: 「`just run` 緑 + `just e2e-test <NAME>` 緑 + スクショ確認 OK」までを 1 セットにする
