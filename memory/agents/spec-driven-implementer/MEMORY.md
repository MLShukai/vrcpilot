# spec-driven-implementer メモリ

`src/vrcpilot/` 配下のプロダクションコードを仕様通りに書くことだけに集中するエージェントの罠集。テストには触らないので、テスト記述慣習は [`agents/spec-test-author/`](../spec-test-author/MEMORY.md)、リファクタは [`agents/code-quality-reviewer/`](../code-quality-reviewer/MEMORY.md)、docstring は [`agents/docstring-author/`](../docstring-author/MEMORY.md)。

shared な規約 ([private モジュール規約](../../feedback_private_module_convention.md)、[lint ツーリング集約](../../feedback_lint_tooling.md) など) は [`memory/MEMORY.md`](../../MEMORY.md) を経由。

## feedback（pyright strict / import / リソース管理 / 並列 hook）

- [Submodule attribute collision in cli package](feedback_submodule_attribute_collision.md) — re-exports clashing with subcommand submodule names get clobbered; rebind after `_main` import
- [yaml.safe_load returns Unknown under pyright strict](feedback_yaml_safe_load_pyright_strict.md) — cast to `dict[str, Any]` after isinstance narrow so int()/str() coercions type-check
- [dict.get on isinstance-narrowed Any returns Unknown under pyright strict](feedback_pyright_strict_untyped_dict_get.md) — rebind through `dict[Any, Any]` alias after narrow; annotate LHS as `: Any`
- [Factory-method seam for COM/native test substitution](feedback_factory_seam_pattern.md) — COM/WGC や native 拡張 (proc-tap 等) は `_open_session` / `_open_capture` factory + duck-typed fake で差し替え可能にする
- [ExitStack for partial-init resource unwind](feedback_exitstack_partial_init_cleanup.md) — multi-step backend constructors use ExitStack + pop_all() instead of nested try/except pyramids; rollback helpers double as close() steps
- [OSC view modules — importing SupportsBool eagerly causes a real circular import](feedback_osc_view_circular_import.md) — `osc/avatar.py` / `controller.py` から `SupportsBool` を取るときは TYPE_CHECKING 下で。`from __future__ import annotations` は annotation しか遅延しない
- [Subclass exception except-order](feedback_exception_subclass_except_order.md) — `VRChatMultipleInstancesError` は `VRChatNotRunningError` / `RuntimeError` より先に except する
- [docformatter は Japanese 全角句点を . に置換](feedback_docformatter_japanese_summary.md) — summary を `。"""` で終わらせると `。."""` に書き換えられ wrapping が走って 2 行に折れる。ASCII `.` で締める
- [Parallel fixer file-scope isolation](feedback_parallel_fixer_isolation.md) — 並列 fixer 実行時は commit 前に out-of-scope ファイルを reset。pre-commit の stash/restore で他 fixer の在庫を引き込みうる
- [e2e PyAV-recorder pattern](feedback_e2e_pyav_recorder_pattern.md) — `tests/e2e/_pyav_recorder.py` に小さな PyAV helper を置く。CLI 内部 muxer を import しない。クラス名は `_` で始めない
- [Platform-specific helpers placement](feedback_platform_specific_helpers_placement.md) — `sink_name_for` のような platform 固有概念のヘルパは `<modality>/<platform>.py` 内に定義。base.py には置かない（非 platform 環境から見えてしまう）

## reference

- [soundcard library quirks](reference_soundcard_quirks.md) — argv probe crashes on empty argv, no public Speaker type, player()/recorder() are context managers, fakes carry `FakeSoundCard*` prefix
