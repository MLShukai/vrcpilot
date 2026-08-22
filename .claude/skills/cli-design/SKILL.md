---
name: cli-design
description: vrcpilot CLI (src/vrcpilot/cli/) の実装規約。thin module (register / run) 構成と _COMMANDS 登録、_common.py の共有ヘルパ (add_pid_arg / resolve_screenshot / emit_yaml / attach_completer)、exit code 0/1/2 と stdout/stderr の役割、multi-action サブコマンドの nested subparser、platform 条件付き登録、テストの patch seam、追加時の docs 更新義務。新しいサブコマンドを足す / 既存の CLI 引数や出力形式を変える前に読む。
---

# vrcpilot CLI の実装規約

`src/vrcpilot/cli/` にサブコマンドを足す / 変えるときの規約。CLI を **使う側** の参照 (サブコマンド表・パイプライン・座標系) は [vrcpilot-cli](../vrcpilot-cli/SKILL.md)、ユーザー向けリファレンスは [docs/cli.md](../../../docs/cli.md)。

## 1. thin module 構成

1 サブコマンド = 1 ファイル `cli/<name>.py` (複数ファイルに割れるなら `cli/<name>/` パッケージ。現状 `record/` だけ)。各モジュールが公開するのはこの 2 つだけ:

```python
def register(subparsers: SubParsersAction) -> None: ...
def run(args: argparse.Namespace) -> int: ...
```

- `register` は subparser を足すだけ。`set_defaults(func=...)` は使わない
- dispatch は [cli/\_\_init\_\_.py](../../../src/vrcpilot/cli/__init__.py) の `_COMMANDS` dict が `args.command` で引く
- `run` は exit code を返す。`sys.exit` を呼ばない (テストが `main()` を in-process で駆動するため)
- サブコマンドモジュールに `__all__` は書かない (`cli/__init__.py` だけが持つ)

**新規登録**: `_COMMANDS` に 1 行足す。**dict の挿入順が `--help` とシェル補完の並び順** になるので、意味のある位置に入れる。

## 2. platform 条件付きサブコマンド

その platform にしか実装が無いサブコマンドは `cli/__init__.py` 側で条件付き登録する。`vrcpilot --help` に実装の無いコマンドを出さないため:

```python
if sys.platform == "linux":
    from . import linux_mic
    _COMMANDS["linux-mic"] = linux_mic
```

モジュール本体の冒頭にも `if sys.platform != "linux": raise ImportError(...)` を防御的二重ガードとして置く。さらに `linux_mic` は platform 固有の重い依存 (`vrcpilot.mic.linux` → pulsectl) を **関数内 import** に遅らせている。それ以外の `cli/*.py` は module top で絶対 import している (`from vrcpilot.window import focus`)。同一サブパッケージ内の `_common` だけ相対 import (`from ._common import ...`) → [memory/feedback_import_style.md](../../../memory/feedback_import_style.md)。

## 3. `_common.py` の共有ヘルパを使う

新しい引数を足す前に [cli/\_common.py](../../../src/vrcpilot/cli/_common.py) に既にあるか確認する。同じ contract を 2 通りに書かない。

| ヘルパ                                            | 用途                                                                               |
| ------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `SubParsersAction`                                | `register` の型注釈。argparse が公開しない subparsers action の別名                |
| `add_pid_arg` / `handle_multi_instance_error`     | `--pid` フラグと、多重起動時の統一 exit-1 診断。PID 依存コマンドは必ずこの組で書く |
| `add_screenshot_input_arg` / `resolve_screenshot` | `-s/--screenshot <yaml>` と stdin pipe の入力解決 (file が stdin に勝つ)           |
| `attach_completer`                                | argcomplete の completer 束縛。pyright-strict のノイズを 1 箇所に閉じ込める        |
| `emit_yaml`                                       | YAML を stdout へ。**素の `print` / `yaml.safe_dump` で書かない**                  |

`emit_yaml` が必須な理由: `sys.stdout.write` は端末のコードページ (日本語ロケール Windows の cp932) で再エンコードされ、pipe / リダイレクト先が UTF-8 を期待していると壊れる。`emit_yaml` は `sys.stdout.buffer` へ UTF-8 バイトを書く。

## 4. 入出力チャネルと exit code

- **結果は stdout**、**診断は stderr**、**成否は exit code**。成功は原則 silent (`focus` / `unfocus` / `osc` 等)
- `vrcpilot: <message>` の 1 行が stderr 診断の統一形式

| code | 意味                                                                                                                                                     |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0`  | 成功                                                                                                                                                     |
| `1`  | 回復可能な失敗 (guard 失敗、VRChat 未起動、多重起動で `--pid` 無し、入力 YAML の不正)                                                                    |
| `2`  | **入力の形が違う**: tty かつ引数なしで stdin を読めない (`paste` / `osc chatbox`)、`-o` の拡張子がモードと不一致 (`record`)、`--fps` と `--audio` の併用 |

argparse が弾く usage エラー (未知のフラグ、必須引数欠落) は argparse 自身が exit 2 を返す。`run` の中で再実装しない。

**新しい exit code を発明しない。** 3 以上を使いたくなったら、それは `1` か `2` のどちらかに分類できるはず。

## 5. multi-action サブコマンド

`osc` (7 アクション) / `speaker` (`list` / `route`) / `mic` / `linux-mic` は nested subparser を使う:

```python
actions = parser.add_subparsers(dest="<name>_action", required=True)
```

`run` の中で `args.<name>_action` を見て private ヘルパ (`_run_list` / `_run_route`) へ振る。flat 設計 (positional action) を選んだサブコマンドを後から subparser 化して文法を変えない。

`osc` は `choices=` に列挙した名前を `getattr(controller, _to_method(name))(...)` で解決している。ボタン / 軸を足すときは `vrcpilot.osc` 側の名前リストが単一の真実であり、CLI 側に名前を再掲しない。

## 6. テストの patch seam を残す

テストは 3rd-party や実 OS 資源をモックせず、**モジュールが公開する 1 つの seam** に fake を束ねる ([vrcpilot-testing](../vrcpilot-testing/SKILL.md))。既存の seam:

- `cli/mouse.py` → `mouse_api` (`from vrcpilot.controls import mouse as mouse_api`)
- `cli/keyboard.py` → `keyboard_api`
- `cli/osc.py` → `_make_sender` ファクトリ

新しいサブコマンドでも同じ形にし、**module docstring に「テストはこの symbol を patch する」と明記する**。import 形を変えると seam が消えてテストが壊れるので、リネーム時は必ずテスト側も確認する。

## 7. argcomplete

- `cli/__init__.py` 冒頭の `# PYTHON_ARGCOMPLETE_OK` と `argcomplete.autocomplete(parser)` が有効化している
- パス引数には `attach_completer(action, FilesCompleter(allowednames=("png",), directories=True))` を付ける
- `build_parser()` は副作用なしで parser を返す (テストと argcomplete が実行せずに検査するため)

## 8. `--viz` のような optional-value フラグ

「フラグ無し / 値なしフラグ / 値ありフラグ」の 3 状態を区別するには sentinel を使う ([cli/ocr.py](../../../src/vrcpilot/cli/ocr.py) が手本):

```python
_VIZ_DEFAULT: object = object()
parser.add_argument("--viz", nargs="?", const=_VIZ_DEFAULT, default=None, type=Path)
```

`type=` はユーザーが値を渡したときだけ適用されるので、`args.viz` は `None` / sentinel / `Path` のいずれかになる。

## 9. 追加したら更新するもの

サブコマンドや引数を足したら、同じ PR で以下を揃える。片方だけ直して終わらない:

1. `tests/vrcpilot/cli/test_<name>.py` (ミラーレイアウト)
2. [docs/cli.md](../../../docs/cli.md) **と** [docs/cli.ja.md](../../../docs/cli.ja.md) の対訳ペア → [write-docs](../write-docs/SKILL.md)
3. `README.md` / `README.ja.md` のサブコマンド表 (`_COMMANDS` が真。drift しやすい)
4. 実機で振る舞いを確認するなら `tests/e2e/` にシナリオを足す
5. [vrcpilot-cli](../vrcpilot-cli/SKILL.md) のサブコマンド表
