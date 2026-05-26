---
name: import-style
description: src/vrcpilot/ 内の import スタイル規約。サブパッケージ内 (兄弟モジュール) は相対 import、別の名前空間は絶対 import、迷ったら絶対。
metadata:
  type: feedback
---

`src/vrcpilot/` 配下の import 文は以下のルールに従う。

## ルール

1. **密結合のサブパッケージ内参照 → 相対 import** (`from .x import Y`)

   - 同じディレクトリ (= 同じ最末端パッケージ) にあるモジュール同士の参照は相対。
   - 例: `vrcpilot/controls/keyboard/linux.py` から `vrcpilot/controls/keyboard/base.py`
     を参照するなら `from .base import Key, Keyboard`。`vrcpilot.controls.keyboard.base`
     を絶対で書かない。
   - `__init__.py` がサブパッケージ内の兄弟モジュールから再 export する場合も `.base` / `.session`
     のように相対で書く。

2. **同じパッケージ内でも別の名前空間 → 絶対 import** (`from vrcpilot.<pkg> import ...`)

   - サブパッケージ境界を跨ぐなら絶対。「兄弟ではない」「親パッケージから降りる必要がある」場合は
     絶対と判定する。
   - 例: `vrcpilot/controls/keyboard/base.py` から `vrcpilot/controls/guard.py` を参照する場合、
     `controls/guard.py` は `controls/keyboard/` の兄弟ではないので
     `from vrcpilot.controls.guard import ensure_target` (絶対) と書く。
   - 例: `vrcpilot/speaker/routing/router.py` から `vrcpilot/speaker/base.py` を参照する場合も
     絶対 (`speaker.base` と `speaker.routing.router` は別名前空間)。

3. **迷ったら絶対 import**

   - 上記 1 / 2 のどちらにも見えるエッジケース (例: 兄弟だが循環参照を避けるため遅延 import している、
     等) は絶対を選ぶ。grep しやすく、リファクタリング時の壊れ方が明示的。

## Why

- 相対 import を「サブパッケージ内の密結合」に限定することで、ファイルを見たときに
  「これは同じディレクトリ内で閉じている」というシグナルとして機能する。
- 絶対 import が出てきたら「subpackage 境界を跨いでいる = 公開 API 相当の依存」と一発で読める。
- 中間 (兄弟でも絶対で書く) を許すと、grep / rename / ファイル移動時の判断がブレる。
  Python 公式 (PEP 328) も「明確な相対 import」を兄弟参照で推奨しているが、本リポジトリは
  「兄弟は相対、それ以外は絶対」の二択に固定する。

## How to apply

- `src/vrcpilot/` 配下を新規/編集する際は import 文ごとに「同じサブパッケージ内か?」を
  判定する。
- サブパッケージ = 同じ `__init__.py` を共有するディレクトリ。`controls/keyboard/` と
  `controls/mouse/` は別サブパッケージ (それぞれ独自の `__init__.py` を持つ)。
- `..` で親パッケージへ上昇する形 (例: `from .._common import ...`) は
  「親も含めて 1 つの責務クラスタ」と見なせる場合は相対 OK。
  例: `cli/record/__init__.py` が `cli/_common.py` を参照する場合、`cli/record/` は
  cli サブコマンドをファイル分割しただけの構造で、`cli/_common.py` は cli 全体の
  共有ヘルパなので、両者は同一の「cli 責務クラスタ」に属する → `from .._common import ...`
  を使う。
- 逆に親パッケージが別責務領域なら絶対にする。判定が曖昧なら「迷ったら絶対」に従う。
- `__init__.py` 内で `from . import a, b` のように兄弟モジュールをまとめて再 export する形は OK。
- テストコード (`tests/`) は常に絶対 import で書く (\[\[test-layout-mirror\]\] でミラー
  レイアウトを採るので、test 側に相対 import の必然性はない)。
