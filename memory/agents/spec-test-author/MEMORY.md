# spec-test-author メモリ

`tests/` 配下のテストコード専任エージェントが、仕様を実行可能な形に翻訳する際の規約と判断材料。**2026 年に方針が大きく改訂**され、3rd-party ライブラリ表面のモックは禁止、`tests/fakes/` は縮小方向。ルール本体は [`.claude/agents/spec-test-author.md`](../../../.claude/agents/spec-test-author.md) と [`vrcpilot-testing` skill](../../../.claude/skills/vrcpilot-testing/SKILL.md) が一次資料で、ここには「会話を跨いで蓄積した固有の判断」のみを残す。

shared な前提 ([テスト戦略 4 区分と新モック方針](../../feedback_test_strategy.md)、[tests ミラーレイアウト](../../feedback_test_layout_mirror.md)、[private モジュール規約](../../feedback_private_module_convention.md)) は [`memory/MEMORY.md`](../../MEMORY.md) を経由。`src/` を編集する権限は無いので、実装側の罠は [`agents/spec-driven-implementer/`](../spec-driven-implementer/MEMORY.md)、リファクタは [`agents/code-quality-reviewer/`](../code-quality-reviewer/MEMORY.md)、docstring 慣習は [`agents/docstring-author/`](../docstring-author/MEMORY.md)。

## feedback（テスト記述ルール — 新方針に整合済み）

- [Test class organization in vrcpilot](feedback_test_classes.md) — `class Test<Target>:` でグルーピング、return-type annotation 無し、`mocker: MockerFixture`
- [自前 ABC fake への boundary assertion は実装テストではない](feedback_boundary_assertions.md) — fake が受け取った load-bearing な引数 (OSC address, target PID, save path) の assertion は契約テストとして OK。3rd-party 表面はそもそもモック自体が禁止
- [Avoid object-typed fixture parameters](feedback_fixture_typing.md) — mock fixture パラメータに `: object` を付けない (pyright ignore ノイズの原因)
- [自前 ABC fake は単一消費者でも tests/fakes/ に集約する](feedback_shared_fakes_in_tests_fakes.md) — 自前 ABC は単一消費者でも `tests/fakes/`。3rd-party 表面 fake は新規追加禁止
- [3rd-party 表面 fake は cleanup target / 自前 ABC fake は使用面のみミラー](feedback_fakes_mirror_production.md) — 3rd-party 表面 fake は新規禁止 + 既存も整理対象。自前 ABC fake は production 呼び出し面のみミラー
- [自分のコードの内部関数モック禁止の実例 (controls 周辺)](feedback_no_internal_function_mocks.md) — ensure_target / resolve_pid / window.\* / is_wayland_native / get_vrchat_window_rect / time.sleep は autouse fixture / 実 X11 / e2e で代用するパターン集
