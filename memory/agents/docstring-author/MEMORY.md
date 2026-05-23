# docstring-author メモリ

docstring / コメント記述専任エージェントが Google-style docstring を書く際の規約と、各サブシステムを文書化するときに知っておくべき固有事情。ロジックには触らないので、実装上の罠は [`agents/spec-driven-implementer/`](../spec-driven-implementer/MEMORY.md) を参照。ユーザー像は [`memory/user_role.md`](../../user_role.md) を参照。

## feedback（記述ルール）

- [No shell tool in docstring-author agent](feedback_environment_no_shell.md) — `just` や `git` は実行できないので検証はユーザーに戻す
- [Don't restate Returns in the docstring summary paragraph](feedback_docstring_returns.md) — 戻り値の契約は `Returns:` ブロックだけに書き、summary に重複させない

## project（vrcpilot サブシステムを文書化する観点）

- [vrcpilot project purpose](project_purpose.md) — VRChat automation library; launcher は基盤で、自動化エントリポイントとして文書化する
- [Capture vs Screenshot API split](project_capture_screenshot_split.md) — streaming vs one-shot pixel surface, Wayland asymmetry, latest-only read
- [vrcpilot.controls subpackage shape](project_controls_subpackage.md) — template-method ABC, lazy backend singleton, ensure_target Wayland-fail-fast
- [vrcpilot CLI subcommand docstring conventions](project_cli_subcommand_style.md) — module/patch-target/register/run shape and exit-code prose pattern

## reference（外部ツール・ライブラリ表現）

- [pytest --doctest-modules is enabled](reference_pytest_doctest_modules.md) — `src` の docstring に書いた `>>>` はテストで実行される
- [docformatter and pyright caveats for docstring work](reference_tooling.md) — docstring 観点の docformatter リフロー挙動と pyright strict 制約。一般論は [`memory/feedback_lint_tooling.md`](../../feedback_lint_tooling.md)
- [Mic modality docstring conventions](reference_mic_docstring_conventions.md) — soundcard error-set, id/name divergence, libpulse/WASAPI wording, lazy-import comment template
