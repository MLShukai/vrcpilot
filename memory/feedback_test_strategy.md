---
name: テスト戦略 4 区分と新モック方針
description: vrcpilot テストは unit/integration-with-fakes/integration-real/e2e の 4 区分。自前 ABC 以外の fake は禁止 (新方針)。プラットフォーム依存はファイル先頭で skip
metadata:
  type: feedback
---

vrcpilot のテストは以下の 4 区分で組み立てる。区分が決まればモック許容度・配置・スキップ方法が一意に決まる。**2026 年に方針が大きく改訂され、3rd-party ライブラリ表面のモックは禁止**になっている。詳細は [`/vrcpilot-testing` skill](../.claude/skills/vrcpilot-testing/SKILL.md) と [`.claude/agents/spec-test-author.md`](../.claude/agents/spec-test-author.md) が一次資料。

| 区分                   | 配置                                                                                | 検証対象                            | モック許容                                                       |
| ---------------------- | ----------------------------------------------------------------------------------- | ----------------------------------- | ---------------------------------------------------------------- |
| unit                   | `tests/vrcpilot/test_<file>.py`                                                     | 純粋ロジック                        | なし                                                             |
| integration-with-fakes | 同上、`tests/fakes/` から **自前 ABC** の fake を import                            | モジュール間結合 (ABC 越し)         | **自前 ABC のみ** (`FakeCapture`, `FakeOCREngine`, `FakeMic` 等) |
| integration-real       | `test_<windows\|linux>.py` / `window/test_*` / `capture/test_{windows,linux}.py` 等 | adapter / 3rd-party 結合点 (実環境) | 原則なし。実 daemon / Xvfb / loopback / 実 subprocess / 実 PNG   |
| e2e                    | `tests/e2e/`                                                                        | 実 VRChat                           | なし                                                             |

## 検証対象の優先順位 (Don't mock what you don't own)

1. **実 resource** — `tmp_path`、実 subprocess の `sleep` / `echo`、loopback UDP、Xvfb、PipeWire null-sink、実 PNG fixture を実 OpenCV / RapidOCR に通す
2. **自前 ABC の fake** — `OCREngine`, `DetectEngine`, `Capture` / `CaptureLoop`, `Mic`, `Speaker` / `SpeakerLoop`, `OscSender` 等 vrcpilot が所有する抽象の差し替え
3. **3rd-party ライブラリ表面のモックは禁止**: `pulsectl.Pulse`, `soundcard.*`, `subprocess.Popen`, `psutil.process_iter` / `psutil.Process`, `windows_capture.WindowsCapture`, `Xlib.display.Display`, `pyperclip.copy`, `proctap.*`, `inputtino.*`, `pydirectinput.*`, `time.sleep` 等
4. **自分のコードの内部関数モックも禁止**: `vrcpilot.controls.*.ensure_target`, `vrcpilot.process.pid.find_pids` 等を直接 `mocker.patch` で置き換えない

## スキップ階層 — ファイル先頭の module-level skip

プラットフォームやディスプレイに依存するテストは **import より前** に `pytest.skip(..., allow_module_level=True)` を置く。関数単位の `@pytest.mark.skipif` だけだと、Linux runner で `import win32gui` のような import 自体が失敗して収集エラーになる。

```python
# 例: tests/vrcpilot/test_linux.py
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux-only module", allow_module_level=True)

from tests.helpers import has_x11_display  # noqa: E402

if not has_x11_display():
    pytest.skip("X11 display unavailable", allow_module_level=True)

# 以降で本物の Xlib を import して使う
```

## `sys.platform` の monkeypatch は禁止

偽のクロスプラットフォーム保証になる。代わりに `tests/helpers.py` の `only_windows` / `only_linux` / `requires_x11_display` を使うか、ファイル分割 + module-level skip にする (旧方針では fail-fast `NotImplementedError` 検証のみ例外扱いだったが、新方針は一律禁止)。

## tests/fakes/ は縮小方向

- `tests/fakes/` には **自前 ABC の fake のみ**残す
- **新規追加禁止**: 3rd-party ライブラリ表面のミラー (`FakePulse*`, `FakeSoundCard*`, `FakeWindowsCapture`, `FakeXDisplay*`, `FakePopen`, `FakeProcess`, `FakePyDirectInput`, `FakeInputtino*`, `FakeMkv/Mp4/Wav` Muxer, `FakeProcessAudioCapture`, `FakePwRecordProcess` 等)
- 既存の 3rd-party 表面 fake は整理対象 (別タスクで段階的に integration-real へ移行)
- 共有 fake は `tests/fakes/{capture,ocr,...}.py` に集約し、テスト側は `from tests.fakes import FakeFoo` で明示 import
- fake の表面を広げる必要が出たらテストファイル内でサブクラス化せず正典クラス側に追加する

## How to apply

新しいテストを書く前に区分を決める:

1. 純粋ロジック (環境依存ゼロ) → unit。モック不要
2. 外部協力者を差し替えないと書けない → integration-with-fakes。**自前 ABC** に限る。fake が無ければ `tests/fakes/` に追加する (3rd-party 表面 fake は追加しない)
3. 3rd-party の挙動依存ロジック → integration-real。Xvfb / PipeWire null-sink / loopback UDP / 実 subprocess / 実 PNG fixture。infra が未整備なら orchestrator に報告
4. 実 VRChat 必須 → `tests/e2e/<scenario>.py` として書き、`just e2e-test <name>` で実行

関連: [feedback_test_layout_mirror.md](feedback_test_layout_mirror.md), [feedback_private_module_convention.md](feedback_private_module_convention.md), [feedback_e2e_run.md](feedback_e2e_run.md)
