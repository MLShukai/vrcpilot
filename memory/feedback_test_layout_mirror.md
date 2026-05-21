---
name: tests は src をミラーリング
description: tests/ ディレクトリは src/vrcpilot/ の構造を 1 対 1 で映す
type: feedback
---

`tests/` のレイアウトは `src/vrcpilot/` をそのままミラーリングする:

- `src/vrcpilot/foo.py` ↔ `tests/vrcpilot/test_foo.py`
- `src/vrcpilot/__init__.py` ↔ `tests/vrcpilot/test_init.py`
- `src/vrcpilot/sub/bar.py` ↔ `tests/vrcpilot/sub/test_bar.py`
- `tests/` 直下に置くのは `__init__.py` / `helpers.py` / `conftest.py` / `manual/` のみ
- 1 ファイル 1 テストを原則とし、`window/{win32,x11}.py` のように複数バックエンドが分かれているソースはテストも分けて 1 対 1 を維持する

**Why:** ソースとテストが 1 対 1 で対応していると、(1) ある source ファイルに対するテストの所在が即座にわかる、(2) 1 つのテストファイルが複数ソースをまたぐ乱雑さを防ぐ、(3) パッケージ追加時にテスト配置で迷わない。flat 配置は最初こそ楽だが、サブパッケージが増えると見通しが悪化する。

**How to apply:** テストを書く・移動する時は、対応 source の相対パスをそのまま `tests/vrcpilot/` 配下にコピーし、`<file>.py` を `test_<file>.py` に置き換える。複数 backend/実装を 1 ファイルでテストしている既存テストを見つけたら、ソース側の分割に合わせてテストファイルも分割する。テスト追加時に対応する `tests/vrcpilot/<sub>/__init__.py` が無ければ作成する（空ファイルで OK）。
