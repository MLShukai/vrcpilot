---
name: tests/fakes は production の表面のみミラーする
description: production が呼ばないシンボルを fake に残すと dead code になりレビューで剥がす対象
type: feedback
---

`tests/fakes/` 配下の test double は **production code が実際に呼び出すメソッド・属性のみ**をミラーする。production が叩かないシンボルを fake に持たせると、grep しても呼び出し元が無いことに気付かれず dead code として埋もれる。

**Why:**

- `tests/fakes/inputtino.py` の冒頭 docstring が「The fakes mirror the real method signatures (verified against the installed inputtino binding)」と明示しており、これは `inputtino` という外部 SDK の API 表面に対する mirror を意味する
- 一方で `FakePyDirectInput` のように **production が高レベル helper (例: `pydirectinput.press`) を使わなくなった**結果、fake 側のメソッドが dead code になるケースがある
- ABC から `_do_press` のような中間メソッドを撤去するリファクタは特にこの dead code を生みやすい (backend が helper API を呼ぶ理由が消える)

**How to apply:**

- ABC のメソッドを撤去するリファクタをレビューする際は、必ず `tests/fakes/` 内で「対応する production 呼び出しが消えた fake メソッド」が無いか grep する
- 残骸 fake を見つけたら削除し、docstring に「Only the surface that production code actually invokes is mirrored」と明示することで、将来また外部 SDK の全 API を移植したくなる衝動を抑える
- 削除する際は touch 範囲の衝突に注意: pydirectinput / inputtino fake は **mouse と keyboard の両方**が共有するので、削除対象が両方でゼロ参照であることを `grep -rn` で確認してから手を入れる
