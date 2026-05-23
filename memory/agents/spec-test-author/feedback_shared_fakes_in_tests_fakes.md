---
name: 自前 ABC fake は単一消費者でも tests/fakes/ に集約する
description: 自前 ABC の fake は最初の消費者が 1 つでも tests/fakes/ に置く。3rd-party 表面のミラー fake は新方針で新規追加禁止
metadata:
  type: feedback
---

**自前 ABC** (vrcpilot が所有する `Capture`, `OCREngine`, `Mic`, `Speaker`, `OscSender`, `Mp4FrameSink` などの抽象) の fake は、たとえ消費者が現状 1 ファイルだけでも `tests/fakes/` に置き、`from tests.fakes import FakeFoo` で import する。ad-hoc な `_Fake<PublicClass>` をテストファイル内で定義しない。

**Why:**

- 共有 fake が `tests/fakes/` に集約されていると、複数テスト間で振る舞いの一貫性を保てる。最初の消費者が 1 つでも、将来 2 つ目が必ず現れる
- 一方、**3rd-party ライブラリの表面をミラーした fake は新方針で新規追加禁止**。`FakePulse*` / `FakeSoundCard*` / `FakeWindowsCapture` / `FakeXDisplay*` / `FakePopen` / `FakeProcess` / `FakePyDirectInput` / `FakeInputtino*` / `FakeMkv*` / `FakeMp4*` / `FakeWav*` Muxer / `FakeProcessAudioCapture` / `FakePwRecordProcess` 等。これらは既存分も整理対象 (integration-real への移行)。よって "shared fake" 規約は 3rd-party 表面に対しては適用しない (そもそも書かない)

**How to apply:**

- 自前 ABC の fake が必要になったとき: `tests/fakes/<topic>.py` に追加 → `tests/fakes/__init__.py` の re-export と `__all__` に登録 → クラス名は `FakeFoo` (先頭 `_` なし。ファイルは private でもクラスは shared)
- レビューで `_Fake<自前 ABC クラス名>` を見つけたら `tests/fakes/` 移動を指示
- レビューで 3rd-party ライブラリ表面の新規 fake を見つけたら **追加を止め**、integration-real (実 daemon / Xvfb / loopback UDP / 実 subprocess) に書き直す方向を提示

関連: [feedback_fakes_mirror_production.md](feedback_fakes_mirror_production.md)、root の [feedback_test_strategy.md](../../feedback_test_strategy.md)
