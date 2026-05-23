---
name: 自前 ABC fake への boundary assertion は実装テストではない
description: 自前 ABC fake が受け取った引数 (load-bearing な call args) の assertion は契約テストとして OK。3rd-party 表面のモックは新方針で禁止なので boundary assertion の対象にもならない
metadata:
  type: feedback
---

「内部実装の詳細をテストしない」というルールは、**自前 ABC fake が受け取った load-bearing な call args** を assert することを禁じない。

**Why:** 区別は assertion が *何* を検証しているか。`FakeOscSender.last_address == "/avatar/parameters/Foo"` のような assertion は **vrcpilot ↔ 自前抽象の契約** を検証している (公開境界に正しい値が届くか)。一方、内部 helper の呼び出し回数や中間状態を assert すると、振る舞いを保つ正当なリファクタで壊れる。前者は refactor を生き残り、後者は生き残れない。

**How to apply:**

- assertion 対象が **自前 ABC の fake** (`FakeOscSender`, `FakeCapture`, `FakeOCREngine`, `FakeMic`, `FakeSpeaker` 等) で、load-bearing な引数 (送信アドレス、保存パス、フレーム数、target PID) を検証している → 受け入れる
- assertion が複数の内部モックの呼び出し順を検証している → push back。振る舞いではなく実装手順をテストしている
- 3rd-party ライブラリ表面 (`win32gui.SetForegroundWindow`, `subprocess.Popen`, `psutil.process_iter`, `Xlib.display.Display` 等) **そもそもモック自体が新方針で禁止**。boundary assertion の対象にもならない。3rd-party 結合の検証は integration-real (実 daemon / Xvfb / loopback UDP / 実 subprocess) で行う

関連: [feedback_shared_fakes_in_tests_fakes.md](feedback_shared_fakes_in_tests_fakes.md), [feedback_fakes_mirror_production.md](feedback_fakes_mirror_production.md), root の [feedback_test_strategy.md](../../feedback_test_strategy.md)
