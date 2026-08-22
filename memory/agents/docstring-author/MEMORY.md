# docstring-author メモリ

docstring / コメント記述専任エージェントが Google-style docstring を書く際の規約と、各サブシステムを文書化するときに知っておくべき固有事情。ロジックには触らないので、実装上の罠は [`agents/spec-driven-implementer/`](../spec-driven-implementer/MEMORY.md) を参照。ユーザー像は [`memory/user_role.md`](../../user_role.md) を参照。

## feedback（記述ルール）

- [Don't restate Returns in the docstring summary paragraph](feedback_docstring_returns.md) — 戻り値の契約は `Returns:` ブロックだけに書き、summary に重複させない

## project（vrcpilot サブシステムを文書化する観点）

- [vrcpilot project purpose](project_purpose.md) — VRChat automation library; launcher は基盤で、自動化エントリポイントとして文書化する
- [Capture vs Screenshot API split](project_capture_screenshot_split.md) — streaming vs one-shot pixel surface, Wayland asymmetry, latest-only read
- [Capture backend lifecycle docstring patterns](project_capture_backend_lifecycle.md) — synchronicity asymmetry, close-race re-check, never-raises close contract, no-unredirect rationale
- [vrcpilot.controls subpackage shape](project_controls_subpackage.md) — template-method ABC, lazy backend singleton, ensure_target Wayland-fail-fast
- [vrcpilot CLI subcommand docstring conventions](project_cli_subcommand_style.md) — module/patch-target/register/run shape and exit-code prose pattern
- [CLI run() exit-code block style](project_cli_exit_code_block_style.md) — single-exit one-liner vs bulleted multi-exit block; pick the second whenever there are 2+ non-zero codes
- [vrcpilot.osc subpackage docstring conventions](project_osc_subpackage.md) — OSC `i`/`f` tag intent, `client=` test seam, `INT_RANGE`/`FLOAT_RANGE`/`CHATBOX_MAX_LENGTH` constants
- [vrcpilot.speaker subpackage docstring conventions](project_speaker_subpackage.md) — PID-isolated capture intent, lazy backend dispatch rationale, drain-all read contract
- [vrcpilot.speaker.linux per-PID design docstring patterns](project_speaker_linux_per_pid.md) — two-stage global-port-id pw-link routing, object.id vs serial trap, pw-dump tempfile race, --target=0 capture side, port-link diagnostic contract, teardown order, trailing-`\s` anchor
- [vrcpilot.speaker.routing subpackage docstring conventions](project_routing_subpackage.md) — relay lifecycle invariants, 3-stage device resolution, error hierarchy, record-vs-routing distinction
- [tests/e2e/ docstring style](project_tests_e2e_docstring_style.md) — scenarios open with "E2E scenario:" + Run with:: block + prerequisites; helpers stay out of that pattern
- [tests/fakes/ docstring style](project_tests_fakes_docstring_style.md) — name the production ABC, why fake vs real, which test tier uses it; reaffirm 3rd-party surfaces are not faked
- [User-docs drift audit checklist](project_user_docs_drift_audit.md) — 5 recurring drift sources to cross-check before declaring a README / CONTRIBUTING / tests/e2e/README polish pass complete

## reference（外部ツール・ライブラリ表現）

- [pytest --doctest-modules is enabled](reference_pytest_doctest_modules.md) — `src` の docstring に書いた `>>>` はテストで実行される
- [docformatter and pyright caveats for docstring work](reference_tooling.md) — docstring 観点の docformatter リフロー挙動と pyright strict 制約。一般論は [`memory/feedback_lint_tooling.md`](../../feedback_lint_tooling.md)
- [Mic modality docstring conventions](reference_mic_docstring_conventions.md) — soundcard error-set, id/name divergence, libpulse/WASAPI wording, lazy-import comment template
