---
name: filesystem / PATH 探索系は HOME / PATH 操作で real-resource 化する
description: shutil.which / Path.expanduser / Path.is_file / Path.read_text を内部で呼ぶ discovery 関数は、shutil や os をモックせず HOME / PATH / 環境変数を操作して実 lookup を走らせる
metadata:
  type: feedback
---

`find_steam_executable` / `find_vrchat_launcher` / `find_umu_launcher` / `linux_steam_paths` のような「filesystem / PATH を探って実体を返す」関数のテストは、`shutil.which` や `Path.read_text` 等の stdlib を mock せず、**環境変数を操作して実 lookup を走らせる**:

**`shutil.which` を相手取る** (PATH 探索):

```python
# Linux 限定: PATH を完全に tmp_path だけにすると、ホストの実 steam を確実に排除できる
monkeypatch.setenv("PATH", str(tmp_path))
# fixture executable を tmp_path に置く
steam = tmp_path / "steam"
steam.write_bytes(b"")
steam.chmod(0o755)
assert find_steam_executable() == steam  # shutil.which が実 lookup で発見する
```

**`Path("~/...").expanduser()` を相手取る** (HOME ベースのパス解決):

```python
# Linux: linux_steam_paths() は ~/.steam/steam と ~/.local/share/Steam を返すので、
# HOME=tmp_path で両 root を tmp_path 配下に閉じ込められる
monkeypatch.setenv("HOME", str(tmp_path))
steam_root = tmp_path / ".steam" / "steam"
# VRChat 配置を steam_root 配下に作る → 実 Path.is_file が発見する
```

**`Path.read_text` を相手取る** (VDF / 設定ファイル parse):

```python
# tmp_path に実 VDF ファイルを書く → parse_steam_library_paths は実 I/O で読む
vdf = tmp_path / "libraryfolders.vdf"
vdf.write_text(_VDF_FIXTURE, encoding="utf-8")
result = parse_steam_library_paths(vdf)  # 実 read_text + 実 regex で動く
```

**Why:**

- `shutil.which` / `os.environ` / `Path.*` は stdlib 表面なので新方針でモック禁止
- `monkeypatch.setenv("PATH", str(tmp_path))` は real PATH lookup を制御下のディレクトリにリダイレクトするだけで、`shutil.which` 自体は本物が動く。実行 path の挙動を 100% 検証できる
- `monkeypatch.setenv("HOME", str(tmp_path))` も同様。`Path("~/.steam/steam").expanduser()` は real lookup が tmp_path 配下を返す
- vrcpilot の `windows_steam_paths` / `linux_steam_paths` を直接 monkeypatch する手もあるが (existing test がそうしていた)、「自分のコードの内部関数モック」のラインに近く、推奨度は HOME 操作の方が高い

**How to apply:**

- 「`shutil.which` の戻り値を mock したい」と思ったら、まず `setenv("PATH", ...)` で代替できないか考える
- 「`linux_steam_paths` を mock したい」と思ったら、`setenv("HOME", tmp_path)` で canonical root を tmp_path 配下に押し込めないか考える
- Windows 側の registry-based discovery (`windows_steam_paths`) は同等の HOME-style 操作が無いので、Windows path は **e2e 担保** にする (Linux runner では実行されない安全な分岐)
- override path のテストは platform-agnostic なので tmp_path だけで十分。OS 限定の auto-detect 経路だけ `@only_linux` / `@only_windows` で区分

関連: shared な [テスト戦略 4 区分](../../feedback_test_strategy.md)
