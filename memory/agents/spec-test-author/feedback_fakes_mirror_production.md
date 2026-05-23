---
name: 3rd-party 表面 fake は cleanup target / 自前 ABC fake は使用面のみミラー
description: 3rd-party 表面 (pydirectinput / inputtino 等) の fake は新規追加禁止で既存も縮小対象。残す自前 ABC fake は production 呼び出し面のみミラーし、dead 化したシンボルは grep で剥がす
metadata:
  type: feedback
---

`tests/fakes/` の運用ルールは新方針で 2 つに分かれる:

- **3rd-party ライブラリ表面の fake** (`FakePyDirectInput`, `FakeInputtino*`, `FakePopen`, `FakeProcess`, `FakeWindowsCapture`, `FakeXDisplay*`, `FakePulse*`, `FakeSoundCard*` 等) — 新規追加禁止。既存分も整理対象で、最終的に integration-real (実 daemon / Xvfb / loopback UDP / 実 subprocess) に移行する
- **自前 ABC の fake** (`FakeCapture`, `FakeOCREngine`, `FakeMic`, `FakeSpeaker`, `FakeOscSender` 等) — 残す対象。**production code が実際に呼び出すメソッド・属性のみ**をミラーする

**Why:**

- 3rd-party 表面 fake は「自分の仮定」をテストするだけで上流変更を検出できない (Don't mock what you don't own)。CI 緑でも実機で死ぬ事故の主犯
- 自前 ABC fake で production が叩かないメソッドを持たせると、grep しても呼び出し元が無いことに気付かれず dead code として埋もれる
- ABC から `_do_press` のような中間メソッドを撤去するリファクタは特にこの dead code を生みやすい (backend が helper API を呼ぶ理由が消える)

**How to apply:**

- 3rd-party 表面 fake が新規に必要に見えたら、**まず integration-real に逃がせないか** (実 daemon spawn / Xvfb / loopback UDP / 実 subprocess) を検討する。書かずに済む方が常に正解
- ABC のメソッドを撤去するリファクタ後は、`tests/fakes/` 内で「対応する production 呼び出しが消えた fake メソッド」が無いか grep する
- 残骸 fake を見つけたら削除し、docstring に「Only the surface that production code actually invokes is mirrored」と明示する
- 削除する際は touch 範囲の衝突に注意: pydirectinput / inputtino fake は **mouse と keyboard の両方**が共有するので、削除対象が両方でゼロ参照であることを `grep -rn` で確認してから手を入れる

関連: [feedback_shared_fakes_in_tests_fakes.md](feedback_shared_fakes_in_tests_fakes.md)、root の [feedback_test_strategy.md](../../feedback_test_strategy.md)
