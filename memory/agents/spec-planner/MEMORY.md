# spec-planner メモリ

仕様策定専任エージェントの参照集。本人はコードを書かないので、ここには「仕様化の判断材料」と「他エージェントへ引き継ぐ際の前提」を残す。

shared なプロジェクト規約・ユーザー像は [`memory/MEMORY.md`](../../MEMORY.md) を経由して参照する (特に [計画ドキュメントは日本語](../../feedback_planning_doc_language.md)、[private モジュール規約](../../feedback_private_module_convention.md)、[tests ミラーレイアウト](../../feedback_test_layout_mirror.md)、[テスト戦略 4 区分](../../feedback_test_strategy.md))。

## reference

- [argcomplete reference facts](reference_argcomplete.md) — v3.6.3, `--shell` choices, FilesCompleter normalization, 1024-byte marker rule

## project（確定した仕様の設計判断）

- [screenshot から mss を除去](screenshot_mss_removal.md) — take_screenshot を Capture へ移行。monitor_index 廃止メカニズム (候補 A: __post_init__)、座標系不変条件、subclass trap、mss 除去 inventory

## archived（過去スコープの設計合意書 — 履歴参照用）

- [Capture / Screenshot 内部設計仕様書](capture_screenshot_internal_design.md) — `feature/capture-screenshot` で 2 並列の `spec-driven-implementer` が衝突しない実装を行うために 2026 年前半に作成した内部設計合意書。当該機能は実装・マージ済みなので **アクティブな仕様ではない**。同じ規模で 2+ エージェントの並列実装を再度仕切る際の **テンプレート例**として残している
