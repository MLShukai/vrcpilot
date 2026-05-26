# code-quality-reviewer メモリ

リファクタリング専任エージェントが `src/vrcpilot/` 内部を public API 不変で整える際の判断材料。`tests/` は触らないので、テスト記述慣習は [`agents/spec-test-author/`](../spec-test-author/MEMORY.md)、docstring 流儀は [`agents/docstring-author/`](../docstring-author/MEMORY.md) を参照。

## feedback（リファクタ判断・型・並行性）

- [Win32 platform narrowing pattern](feedback_win32_narrowing.md) — `if sys.platform != "win32": raise RuntimeError("unreachable")` は pyright 用の narrowing で dead code ではない
- [pyright ignore の集約・最小化](feedback_pyright_ignore_minimization.md) — stub のない C 拡張は 1 度 Any 化して連鎖する `reportUnknown*` を全部消すのが定石
- [重複抽出のタイミング](feedback_dedupe_threshold.md) — 2 つ目を見て I/F が固まってから helper 化。extractor 固有 kwarg で肥大しそうなら 3 つ目まで待つ
- [Producer/consumer exception planting needs same condition](feedback_producer_consumer_exception_race.md) — drain/listener が exception を slot に積むなら、書き込みは consumer が wait する Condition の内側で。check-then-wait は race
- [hot-loop で resolve_pid 禁止 (focus=False)](feedback_hot_loop_no_resolve_pid.md) — controls/clipboard の focus=False 経路では ensure_target/resolve_pid を完全 skip。psutil.process_iter のコスト回避
- [cross-module helper は `_` prefix を付けない](feedback_cross_module_helper_no_underscore.md) — pyright が reportPrivateUsage + reportUnusedFunction を同時に出す。非 `_` 命名 + `__all__` 非登録で両立

## project（vrcpilot 固有の確立パターン）

- [pulsectl session pattern](project_pulsectl_session_pattern.md) — `vrcpilot.mic.linux._pulse_session(client_name)` で `open_pulse_control` → `try/finally close` の boilerplate を集約。pulsectl を使う新規コードはこの CM を経由する
