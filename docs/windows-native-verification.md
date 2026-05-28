# Windows ネイティブバックエンド検証ハンドオフ

このドキュメントは、**Windows 実機の Claude Code セッション**が
`vrcpilot._native`（Rust/PyO3 拡張）の **Windows 専用コードを検証・修正**
するための指示書である。Linux 開発機で実装したが、Windows 専用コードは
`#[cfg(target_os = "windows")]` ゲートのため Linux では一切コンパイル・実行
されず未検証のまま。Windows 機でビルド→修正→`just run`→e2e のループを回す。

ブランチ: `feature/20260529/rust-native-backend`（このブランチを checkout して作業）。

## 0. 背景 — 何がどこまで終わっているか

`vrcpilot` のパフォーマンス critical 経路を Rust(PyO3 拡張 `vrcpilot._native`、
submodule `process` / `window` / `capture` / `speaker`）へ移植中。ビルドは
`hatchling` → **maturin**（abi3-py312、1 wheel/プラットフォームが 3.12-3.14 を
カバー）へ移行済み。

| 項目                                                                | 状態                      | Windows 検証                                        |
| ------------------------------------------------------------------- | ------------------------- | --------------------------------------------------- |
| Phase 0: maturin 足場 / CI / justfile / pre-commit                  | 完了                      | `uv sync` が maturin でビルドできるか               |
| `_native.process.find_pids`（sysinfo）                              | Linux 検証済 + e2e        | **要確認**（下記 §5）                               |
| `_native.window.{focus,unfocus,is_foreground,get_window}_*`（Rust） | Linux(x11rb) 検証済 + e2e | **要実装検証**（`rust/window_windows.rs`、下記 §4） |
| capture / speaker / mic                                             | 未着手（Python のまま）   | 対象外                                              |

Windows 専用 Rust は **`rust/window_windows.rs`** のみ（process は cross-platform な
`sysinfo`）。これが本ハンドオフの主対象。

## 1. 環境セットアップ（Windows 機）

```bash
# Rust toolchain（MSVC）
rustup default stable
rustup component add clippy rustfmt

# uv（未導入なら https://docs.astral.sh/uv/ の手順で）
# just（cargo install just でも可）。justfile は Git Bash 前提
#   （set windows-shell := ["C:/Program Files/Git/bin/bash.exe","-c"]）

just setup        # uv venv + uv sync --all-extras（maturin で _native をビルド）+ pre-commit install
```

`uv sync` の時点で maturin が `rust/` をコンパイルして
`src/vrcpilot/_native.*.pyd` を生成する。**ここで `rust/window_windows.rs` が
初めてコンパイルされる**ので、API 不一致のコンパイルエラーはここで出る。

確認:

```bash
uv run python -c "import vrcpilot; from vrcpilot import _native; print(_native.window.get_window_rect(99999999))"
# -> None（VRChat 未起動）が出れば import + 呼び出し OK
```

## 2. 検証ループ

```
1. cargo build / just rust-check        -> windows crate API 不一致を潰す（§4）
2. just run                              -> pytest（test_windows.py 等）+ pyright を green に
3. just e2e-test <scenario>              -> 実 VRChat で focus/mouse/keyboard を検証（§6）
4. 直したら commit（§7）
```

`just rust-check` = `cargo fmt --check && cargo clippy --all-targets -- -D warnings && uv run cargo test --no-default-features`。
clippy の `-D warnings` で deprecated API も弾かれるので、警告も潰すこと。

## 3. find_pids（process.rs）の Windows 確認事項 — §5

`rust/process.rs` は `sysinfo` で cross-platform。Windows でも動くはずだが、
以下を e2e（`launch_terminate` / `multi_instance`）で確認:

- `p.name()` が `"VRChat.exe"` と **完全一致**するか（Windows の sysinfo は
  実行ファイル名を返すので一致するはず）。一致しなければ `VRCHAT_PROCESS_NAME`
  との比較が 0 件になり全機能が「VRChat 未起動」扱いになる。
- `p.thread_kind().is_none()` フィルタ: Windows ではプロセス一覧にスレッドは
  出ないので全プロセスが `None`。問題ないはずだが、`find_pids()` が
  VRChat.exe 1 件を返すことを `multi_instance` で確認（Linux では Proton の
  スレッドが `VRChat.exe` 名で多数出る問題があり、このフィルタで解決した経緯）。
- `start_time()` で newest-first 並びが効くか（`ProcessRefreshKind::nothing()`
  でも start_time は取れる想定）。

## 4. `rust/window_windows.rs` の高リスク箇所（windows crate 0.62）

Linux 機で windows crate 0.62 の API に当てて書いたが **コンパイル未確認**。
以下は version 差で型・シグネチャがズレやすい箇所。コンパイルエラーが出たら
ここを最初に疑う。修正は `windows` crate のドキュメント / `cargo doc` で確認。

1. **`BOOL` / `TRUE` の import パス**: `use windows::Win32::Foundation::{BOOL, TRUE}`
   としているが、0.62 で `windows::core::BOOL` に移動している可能性。EnumWindows
   コールバックの戻り型が合わなければここを切り替える。
2. **`SetWindowPos` の `hWndInsertAfter`**: `Some(HWND_BOTTOM)` としている。0.62 で
   この引数が `HWND`（非 Option）なら `Some(...)` を外して `HWND_BOTTOM` を直接渡す。
   逆に `Option<HWND>` を要求するならそのまま。
3. **`ShowWindow` / `SetForegroundWindow` の戻り値**: `BOOL` 想定で `let _ =`。
   `Result` を返すバージョンなら `let _ =` のままで可（must_use 警告は出ない）。
4. **`GetWindowRect` / `BringWindowToTop` / `SetWindowPos` / `EnumWindows`**:
   `windows::core::Result<()>` を返す想定（`.is_ok()` / `.ok()?`）。これが `BOOL`
   返しのバージョンなら `.as_bool()` に直す。
5. **`SetThreadDpiAwarenessContext` と `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`**:
   `windows::Win32::UI::HiDpi` に定数がある想定。無ければ `DPI_AWARENESS_CONTEXT(-4)`
   を手で構築（`-4 isize` を newtype に包む）。
6. **`keybd_event` のフラグ**: `KEYBD_EVENT_FLAGS(0)`（押下）/ `KEYEVENTF_KEYUP`。
   `VK_MENU.0 as u8` で u8 に落としている。型が合わなければ調整。
7. **`GetForegroundWindow() == hwnd`**: `HWND` の `PartialEq` 前提。無ければ
   `.0 == hwnd.0`（内部ポインタ比較）にする。
8. **EnumWindows コールバック**: `unsafe extern "system" fn(HWND, LPARAM) -> BOOL`。
   `WNDENUMPROC` の期待シグネチャと一致しているか。`LPARAM(ptr as isize)` /
   `lparam.0 as *mut FindCtx` のキャストも確認。

Cargo.toml の windows feature が足りずに型が見つからない場合は、
`[target.'cfg(target_os = "windows")'.dependencies] windows` の `features` に
不足モジュール（例 `Win32_Graphics_Gdi`）を追加する。現状の features:
`Win32_Foundation`, `Win32_UI_WindowsAndMessaging`, `Win32_UI_HiDpi`,
`Win32_UI_Input_KeyboardAndMouse`。

**重要**: API シグネチャを直すのは OK。ただし**各関数の振る舞い契約（§4.1）と
Python 側（`src/vrcpilot/window/windows.py` / `geometry.py`）・公開 API は変えない**。
Python 側は `_native.window.<fn>(pid)` を呼ぶだけなので基本触らない。

### 4.1 各関数が満たすべき契約（`tests/vrcpilot/window/test_windows.py` がピン留め）

- `focus_window(pid)`: 該当 HWND 無し→`False`。自プロセス所有の可視 top-level が
  あれば前面化して `True`（Alt 押下で SetForegroundWindow ロック回避）。
- `is_window_foreground(pid)`: HWND 無し→`False`。`focus` 直後は `True`。
- `unfocus_window(pid)`: HWND 無し→`False`。あれば `SetWindowPos(HWND_BOTTOM, SWP_NOACTIVATE)` 成功で `True`。
- `get_window_rect(pid)`: HWND 無し→`None`。あれば PER_MONITOR_AWARE_V2 下の
  `GetWindowRect` から `(x, y, width, height)` 物理ピクセル、退化サイズ→`None`。
  **capture（`vrcpilot.windows.get_window_rect`、Python のまま）と同じ値**である
  こと（mouse クリック変換とキャプチャ矩形の整合）。

## 5. 実行するテスト

```bash
just run    # = pre-commit + rust-check + build-native + pytest + pyright
```

- `tests/vrcpilot/window/test_windows.py`: tkinter で実ウィンドウを出し、
  自プロセス PID で focus/unfocus/is_foreground の round-trip を検証
  （`has_working_tkinter()` で skip 階層あり）。**これが Windows 機での
  window バックエンドの主検証**。
- `tests/vrcpilot/test_geometry.py::TestGetVrchatWindowRectWindowsBackend`:
  `pid=99_999_999` で実 EnumWindows 走査 → `None`。
- `tests/vrcpilot/test_process.py`（find_pids 差分テストは Linux/Windows 共通）。

pyright は `src/` を strict で見る（`_native.pyi` のスタブで型解決）。Windows
専用 `.py`（`window/windows.py` 等）も pyright strict 対象なので 0 errors を保つ。

## 6. 実行する e2e（実 VRChat 必須）

Windows で Steam + VRChat を起動できる状態にして以下を順に。各 `PASS:` を確認し、
スクショ（`_e2e_artifacts/<scenario>/.../*.png`）を Read で目視する。

```bash
just e2e-test launch_terminate   # find_pids の spawn/exit 検出
just e2e-test multi_instance     # find_pids が複数 PID を正しく返す + 並び
just e2e-test focus_unfocus      # native focus/unfocus/is_foreground（スクショ目視）
just e2e-test keyboard           # ensure_target 経由（スクショ目視）
just e2e-test mouse              # geometry.get_window_rect 経由の座標変換（スクショ目視）
```

期待: Linux 機では全て PASS 済み。Windows でも同じ挙動になること。特に
`mouse` の "window centre" 移動がウィンドウ内に収まる（= `get_window_rect` の
DPI/座標が正しい）ことをスクショで確認する。

## 7. ブランチ / コミット規約（CLAUDE.md 準拠）

- 作業ブランチ: `feature/20260529/rust-native-backend` 上で続ける（新規に切らない）。
- コミット: `<種別>(<スコープ>): <内容>`。例
  `fix(window): windows crate 0.62 の SetWindowPos シグネチャに追従`。
- コミット末尾に `Co-Authored-By: ...` を付与（CLAUDE.md 参照）。
- `main` へは直接 commit しない。マージはユーザー判断。

## 8. 完了条件

1. `just run` green（pytest 全通過 + pyright 0 errors + cargo fmt/clippy/test green）
2. `just e2e-test launch_terminate / multi_instance / focus_unfocus / keyboard / mouse`
   が全て `PASS:`、スクショ目視で異常なし
3. 直した内容を上記規約で commit

これで `vrcpilot._native` の Windows 検証は完了。capture / speaker / mic の
Rust 化（WS-2 / WS-3）は別タスク。
