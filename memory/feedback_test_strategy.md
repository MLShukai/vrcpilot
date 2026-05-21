---
name: テスト戦略 4 区分とスキップ階層
description: vrcpilot テストは unit/integration-with-fakes/integration-real/e2e の 4 区分。プラットフォーム/ディスプレイ依存はファイル先頭で skip
type: feedback
---

vrcpilot のテストは以下の 4 区分で組み立てる。区分が決まればモック許容度・配置・スキップ方法が一意に決まる。

| 区分                   | 配置                                                                                 | モック         | 環境前提                    |
| ---------------------- | ------------------------------------------------------------------------------------ | -------------- | --------------------------- |
| unit                   | `tests/vrcpilot/test_<file>.py`                                                      | なし           | なし                        |
| integration-with-fakes | 同上、`tests/fakes/` を import                                                       | 統一 fake のみ | なし                        |
| integration-real       | `test_x11.py` / `test_win32.py` / `window/test_*` / `capture/test_{win32,x11}.py` 等 | 最小限         | ディスプレイあり OR 該当 OS |
| e2e                    | `tests/e2e/`                                                                         | なし           | 実 VRChat                   |

## スキップ階層 — ファイル先頭の module-level skip

プラットフォームやディスプレイに依存するテストは **import より前** に `pytest.skip(..., allow_module_level=True)` を置く。関数単位の `@pytest.mark.skipif` だけだと、Linux runner で `import win32gui` のような import 自体が失敗して収集エラーになる。

```python
# 例: tests/vrcpilot/test_x11.py
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import has_x11_display  # noqa: E402

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

# 以降で本物の Xlib を import して使う
```

## モック許容ルール

**OK**:

- `subprocess.Popen` を `FakePopen` で置換（実 Steam を起動しない）
- `psutil.process_iter` を `FakeProcess` リストで置換（実プロセス前提を避ける）
- `windows_capture.WindowsCapture` を `FakeWindowsCapture` で置換（実 VRChat ハンドル必須のため）
- `Xlib.display.Display` を `FakeXDisplay` で置換（X サーバが無い環境のみ。あるなら本物を使う）

**NG（全廃）**:

- `sys.platform` の monkeypatch — 偽のクロスプラットフォーム保証になる。代わりに `@only_windows` / `@only_linux` または module-level skip
- `vrcpilot.cli.launch` / `vrcpilot.cli.terminate` 等、内部結合点を直接モック — CLI が実際に組み立てる argv が無検証になる
- `tests/vrcpilot/**` 内でアドホックに `class _Fake*` を定義する — `tests/fakes/` に集約

## tests/fakes/ の集約原則

- 共有が必要な test double は `tests/fakes/{capture,process,x11}.py` に置く
- テストファイル側では `from tests.fakes import FakeFoo` で明示 import
- fake の表面を広げる必要が出たら、テストファイル内でサブクラス化せず正典クラス側に追加する（例: クラス属性の追加）
- クラス属性を介した状態（`FakeWindowsCapture.last_kwargs` 等）を共有する fake は、各テストパッケージの conftest で per-test サブクラスを生成して isolation を取る

**Why:** ad-hoc モック・`sys.platform` 改変・内部 API モックは 540 箇所まで増殖し、メンテナンスコストと実環境との乖離（CI が緑でも実機で死ぬ）を生んでいた。Phase 2-3 の再設計でこれを駆逐し、158 passed / 20 skipped / pyright clean に到達した。「動くテスト」より「実環境の振る舞いを保証するテスト」を優先する。

**How to apply:** 新しいテストを書く前に区分を決める:

1. 純粋ロジック（環境依存ゼロ）→ unit。モック不要
2. 外部協力者をモックしないと書けない → integration-with-fakes。`tests/fakes/` を import。無ければそこに追加
3. 実環境（Win32 API / X11 ディスプレイ）でしか正しく動かない → integration-real。ファイル先頭に module-level skip
4. 実 VRChat 必須 → `tests/e2e/<scenario>.py` として書き、`just e2e-test <name>` で実行

関連: [feedback_test_layout_mirror.md](feedback_test_layout_mirror.md), [feedback_private_module_convention.md](feedback_private_module_convention.md)
