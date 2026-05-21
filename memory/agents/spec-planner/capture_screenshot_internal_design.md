# Capture / Screenshot 内部設計仕様書

本書は承認済みプラン `vrchat-capture-py-mss-focus-hazy-steele.md` の「公開 API」と「マルチエージェント実行計画」を 2 つの並列 spec-driven-implementer エージェント (Capture トラック / Screenshot トラック) が **衝突せず、独立に** 実装できるようにするための内部設計合意書である。プランで決定済みの公開 API 形状はそのまま採用し、本書ではその下で必要な内部の振る舞い・責任境界・エラー条件・テスト方針を確定する。

用語:

- **Capture トラック**: `src/vrcpilot/capture.py` を `Capture` クラスに書き換え、両 OS 共通の矩形ヘルパを `_win32.py` / `_x11.py` に追加するエージェント。
- **Screenshot トラック**: `src/vrcpilot/screenshot.py` を新規作成するエージェント。Capture トラックが追加した矩形ヘルパを **import するだけ** で、`_win32.py` / `_x11.py` には触れない。
- **frame**: バックエンド (WGC または X11 Composite) から受け取る 1 枚分のピクセル。常に shape `(H, W, 3)`、dtype `uint8`、color order **RGB** の `numpy.ndarray` として `read()` から返される。

要件強度の表記は RFC 2119 の MUST / SHOULD / MAY を用いる。

______________________________________________________________________

## 1. Capture クラスの内部設計

### 1.1 共通インターフェース

#### 1.1.1 `__init__(*, frame_timeout: float = 2.0) -> None`

実行順序 (MUST 厳守):

1. プラットフォーム判定。`sys.platform` が `"win32"` でも `"linux"` でもなければ `NotImplementedError(f"Capture is not supported on {sys.platform}")` を raise して中断する。
2. Linux の場合のみ `is_wayland_native()` をチェック。`True` なら `RuntimeError("Capture requires X11 or XWayland; native Wayland is not supported")` を raise する (Screenshot は warning + None だが、Capture は連続フレーム取得が原理的に成立しないため早期失敗が自然)。
3. `find_pid()` を呼び、`None` の場合は `RuntimeError("VRChat is not running")` を raise する。
4. ウィンドウを解決する。Win32 は `find_vrchat_hwnd(pid)`、Linux は `x11_display()` を **`__init__` の中で開いて、Capture インスタンスがその Display 接続を保持する**。`find_vrchat_window(display, pid)` で X Window を取得する。`None` の場合は `RuntimeError("VRChat top-level window is not yet mapped")` を raise する (Display を開いていれば close してから raise する)。
5. バックエンド (WGC セッションまたは X11 Composite redirect) を起動し、保持リソース一式をインスタンス属性に格納する。バックエンド起動が `OSError` 等で失敗した場合、例外メッセージを保持しつつ `RuntimeError` に変換して raise する。途中で raise する場合は、それまでに獲得したリソース (Display 接続、redirect 状態など) を `__init__` 内で MUST 解放してから raise する。
6. 内部状態 `_closed: bool = False` を最後に立てる。例外で抜けた場合は `False` のままだが、インスタンスは未完成のまま破棄されるため問題ない。

`frame_timeout` は秒単位の浮動小数。`<= 0` の場合は `ValueError("frame_timeout must be > 0")` を raise する。値はインスタンス属性 `_frame_timeout` として保存する。

#### 1.1.2 `read() -> np.ndarray`

戻り値レイアウト:

- shape `(H, W, 3)`、dtype `uint8`、メモリレイアウト C 連続 (contiguous)
- color order は **RGB**。BGRA や BGRX で受け取る場合は内部で変換する
- 配列はバックエンド内部バッファとは独立した copy であること (MUST)。呼び出し元が numpy.ndarray を保持・編集してもバックエンドのキューに影響しないこと。
- フレームサイズが時刻で変わる場合 (ウィンドウリサイズ) は **その回の `read()` がそのリサイズ後のサイズを返す**。動画用途で固定サイズが欲しい場合は呼び出し側でリサイズ責務を持つ。

「次のフレーム」のセマンティクス: **「最新の (最も新しい) 未読フレームを 1 枚返す」** (MUST)。FIFO で古いフレームを消費する設計は採用しない。理由: 動画用途ではキューが詰まると遅延が雪だるま式に膨らむ。Capture の役割は「呼び出された時点の現在に最も近いフレームを返す」こと。バッファに 2 枚以上溜まっていれば古い方は破棄する。

ブロッキング動作:

- バッファに未読フレームがあれば即座に返す。
- バッファが空なら最大 `_frame_timeout` 秒だけ新フレーム到着を待機する。
- タイムアウト時は `TimeoutError(f"No frame arrived within {self._frame_timeout}s")` を raise する。
- close 後の呼び出しは `RuntimeError("Capture is closed")` を raise する。これは MUST であり、close 後に偶然バッファに残っていたフレームを返してはならない (close でバッファをクリアする責務はバックエンド側に持たせる)。

スレッド安全性:

- `read()` は MUST 単一スレッドからのみ呼ばれる前提で十分 (動画ループは普通そうなる)。複数スレッドからの同時 `read()` をサポートする義務はない。
- ただし `close()` は **`read()` をブロックしている別スレッドから呼んでも、`read()` 側がきれいに `RuntimeError` を返して終わるべき** (SHOULD)。これを達成するためには、待機中の `read()` を起こす仕組み (queue.Queue へのセンチネル投入、threading.Event のセット等) が必要。実装上の現実解は 1.2 / 1.3 で具体化する。
- バックエンドのコールバック (WGC の `on_frame_arrived`、X11 ループ) は当然別スレッドで動くため、フレームの受け渡しは MUST スレッドセーフな構造で行う。

#### 1.1.3 `close() -> None`

冪等性: 何回呼んでも安全である (MUST)。2 回目以降は no-op。

リソース解放順序 (MUST 厳守):

1. `_closed = True` を最初にセット。これ以降の `read()` は `RuntimeError` を返す。
2. バックエンド固有の停止処理 (WGC: `control.stop()`、X11: 特になし) を実行。
3. `read()` で待機しているスレッドを起こす (queue にセンチネルを入れる、または Event をセットする)。
4. バックエンドのワーカースレッドを join する (タイムアウトを伴う、上限は `_frame_timeout + 0.5s` 程度)。join できなかった場合は warnings.warn(RuntimeWarning) するが例外は raise しない。
5. プラットフォーム固有のリソース (X11: Pixmap.free / Display.close、Win32: queue クリア) を解放する。
6. 内部バッファを空にする。

`close()` 自身は例外を raise しない (MUST)。下層の例外は `warnings.warn` で表面化させ、`close()` の呼び出し元が例外でハマらないようにする。これは `__exit__` から呼ばれるためでもある。

#### 1.1.4 `__enter__`, `__exit__`

- `__enter__(self) -> Self`: `self` を返すだけ。`__init__` 完了済みの保証あり。
- `__exit__(self, exc_type, exc_val, exc_tb) -> None`: `self.close()` を呼び、`None` (= falsy) を返す。**例外を抑制してはならない** (MUST)。with ブロック内の例外は呼び出し元に伝搬する。

#### 1.1.5 close 後の挙動表

| 操作        | close 後の振る舞い                                                                                                                                          |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `read()`    | `RuntimeError("Capture is closed")`                                                                                                                         |
| `close()`   | no-op (idempotent)                                                                                                                                          |
| `__enter__` | この設計では再利用前提でないので未定義。ただし `__exit__` 経由の二重 close は no-op。明示的に `with` ブロックを 2 回ネストしないよう docstring で MUST 注意 |

### 1.2 Windows (WGC) 側の内部設計

現行の `_take_screenshot_win32` は「`start_free_threaded` → 1 フレーム取得 → `control.stop()`」だが、保持型では `start_free_threaded` を `__init__` で 1 度だけ呼んでセッションを継続させる。

#### 1.2.1 フレーム受け渡し: 単一スロット (latest-only) バッファ + Event

採用方針:

- `threading.Lock` で保護された **単一スロット** `_latest_frame: tuple[np.ndarray, int, int] | None`
- `threading.Event` `_frame_event` で「新フレーム到着」を通知
- `on_frame_arrived` ハンドラの中で:
  1. `frame.frame_buffer.tobytes()` で BGRA バイト列を取得 (現行同様)
  2. `numpy.frombuffer(buf, dtype=uint8).reshape(h, w, 4)` で view
  3. `[..., :3][..., ::-1]` で RGB へ変換、`.copy()` で連続化
  4. lock を取って `_latest_frame` を上書き、Event をセット
- `read()` の中で:
  1. `_frame_event.wait(timeout=_frame_timeout)` で待機
  2. タイムアウト → `TimeoutError`
  3. lock を取って `_latest_frame` を読み出し、`None` 化、`_frame_event.clear()`
  4. ndarray を返す (上で copy 済みなので呼び出し元に安全に渡せる)

この方式の根拠:

- `queue.Queue` で FIFO 蓄積するとフレーム消費が遅れた場合に遅延が累積する。動画用途では「最新フレーム優先」が望ましい。
- 単一スロット + Event は std lib のみで実装でき、依存追加なし。
- バックプレッシャー方針として、ハンドラはブロックせず常に最新のみ保持。古いフレームは捨てる (動画キャプチャの一般的方針)。

#### 1.2.2 ライフサイクル

`__init__` の WGC ステップ (1.1.1 のステップ 5 詳細):

1. `WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)` を生成。
2. `@capture.event` で `on_frame_arrived` と `on_closed` を登録 (現行と同じ)。**`control.stop()` を `on_frame_arrived` 内で呼んではならない** (連続取得のため)。
3. `capture.start_free_threaded()` を呼び、戻り値の `control` をインスタンス属性 `_control` に保存。`OSError` 発生時は `RuntimeError` に変換して raise。
4. `_control.wait()` を別スレッドで呼ぶ必要は **ない**。`start_free_threaded` はその名の通りすでに別スレッドでループしている。Capture は `_control.stop()` 経由で停止する。

`close()` の WGC ステップ (1.1.3 のステップ 2-4 詳細):

1. `_control.stop()` を呼ぶ。これは冪等であることが期待される (windows-capture の API)。
2. `_frame_event.set()` で待機中の `read()` を起こす (起きた `read()` 側は `_closed` チェックで `RuntimeError` を返す)。
3. `_control.wait(timeout=...)` または該当のスレッド合流 API があればそれを呼んで join する。`windows_capture` ライブラリの API として `wait` を join 用に使う前提とする。なければ、warnings + そのまま続行。

#### 1.2.3 ウィンドウリサイズ

`on_frame_arrived` は到着のたびに `frame.width` / `frame.height` を渡してくる。`_latest_frame` のスロットは `(ndarray, w, h)` のタプルなので、リサイズが起きても次の `read()` が新サイズの ndarray を返すだけで自然に対応できる。Capture 側にウィンドウサイズ追跡の追加責務はない。

#### 1.2.4 例外モデル (Win32)

| 状況                                 | 振る舞い                                                                                      |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| `find_pid() is None`                 | `__init__` → `RuntimeError("VRChat is not running")`                                          |
| `find_vrchat_hwnd() is None`         | `__init__` → `RuntimeError("VRChat top-level window is not yet mapped")`                      |
| `start_free_threaded()` が `OSError` | `__init__` → `RuntimeError("Failed to start WGC session: ...")` (元例外を `from` でチェイン)  |
| 初回フレームがタイムアウト           | `read()` → `TimeoutError` (`__init__` ではタイムアウトしない。最初の `read()` で初めて顕在化) |
| close 後 `read()`                    | `RuntimeError("Capture is closed")`                                                           |

### 1.3 Linux (X11 Composite) 側の内部設計

現行の `_take_screenshot_x11` は `with x11_display()` の中ですべて完結しているが、保持型では Display 接続を `__init__` から `close()` まで保持する必要がある。

#### 1.3.1 Display 接続の寿命

- `__init__` の中で `Xlib.display.Display()` を **`with` ではなく直接** open し、インスタンス属性 `_display` に保存する。`x11_display()` のコンテキストマネージャ形式は単発用途のため、Capture では使わない (open 失敗時の `None` 戻りを Capture 側で再現する必要があるが、これは下記参照)。
- 実装の選択肢:
  - 案 A: `_x11.py` に新規ヘルパ `open_x11_display() -> Xlib.display.Display | None` を追加し、open 失敗時に `None` を返す。Capture はこれを使い、`None` の場合は `RuntimeError("X11 display unavailable")` を raise する。
  - 案 B: `__init__` 内で直接 `Xlib.display.Display()` を呼び、既存の例外 (`DisplayError`, `XauthError`, `ConnectionClosedError`, `OSError`) を `RuntimeError` に変換する。
  - **採用: 案 A** (`_x11.py` 内のロジックを既存 `x11_display` と一貫させ、テストモックポイントも統一できる)。Capture トラックが `_x11.py` に追加する責務を負う。

#### 1.3.2 redirect_window と Pixmap の寿命

`redirect_window`:

- 既存実装の通り `composite.RedirectAutomatic` モードで idempotent。コンポジタが既に redirect している環境でも安全。
- `__init__` で 1 回だけ呼ぶ (MUST)。`close()` で **unredirect は呼ばない** (SHOULD): コンポジタが既に redirect している環境で unredirect すると他アプリの描画を壊す可能性がある。`RedirectAutomatic` モードは複数クライアントから安全に呼べるよう設計されているため、leak しても致命的ではない。

`name_window_pixmap`:

- ウィンドウのバッファがリサイズや再マップで作り直されるたびに、それまでに `name_window_pixmap` で取得した Pixmap は無効になる (古いバッファを指す)。
- 採用方針: **`read()` ごとに `name_window_pixmap` を呼び直す** (MUST)。前回の Pixmap は `pixmap.free()` で解放する。これは単発実装と同じパターンの繰り返し。コストは X サーバーへの 1 ラウンドトリップだが、リサイズ追従と引き換えに支払う。
- 代替案 (`__init__` 時の Pixmap を使い回す) は採用しない。理由: ウィンドウリサイズで即座に壊れ、`BadPixmap` エラー経路が増える。

#### 1.3.3 ウィンドウサイズ追跡

`read()` の中で:

1. `_window.get_geometry()` を呼んで現サイズ (width, height) を取得
2. width \<= 0 または height \<= 0 なら `RuntimeError("Window has invalid geometry")` を raise (これは Win32 側との挙動差: Win32 はバックエンドがフレームを送って来ない=タイムアウト経路だが、X11 は能動的に geometry を読みに行くため整合性の取れた raise が可能)
3. `composite.name_window_pixmap(_window)` で新 Pixmap 取得
4. `pixmap.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)` でデータ取得
5. `pixmap.free()` で即座に解放
6. `numpy.frombuffer(reply.data, dtype=uint8).reshape(h, w, 4)` で view、BGRA → RGB へ変換、`.copy()` で連続化して返す

`read()` のタイムアウト: X11 側は同期的に X サーバーから読み出すため、原理的に「フレーム待機」の概念がない。**`read()` のタイムアウトは X サーバーへのリクエスト全体に対する保護として** Display 操作を `_frame_timeout` 秒以内に完了することを期待する形にする。具体的には Python 側でのタイムアウト機構が python-xlib では用意されていないため、`signal.alarm` 等は SHOULD 使わない (移植性低下)。X 操作はブロックすれば長くて数百 ms で返るのが通常で、これを許容する。`TimeoutError` の経路は Win32 専用と考えてよい (X11 は `XError` 経路が中心)。

#### 1.3.4 close() の順序 (X11)

1. `_closed = True`
2. (X11 側にはフレームスレッドがないので join 不要)
3. `_display.close()` を try/except で呼ぶ。例外は warnings.warn で表面化。
4. (Pixmap は `read()` のたびに即解放しているので close 時の解放対象なし)
5. unredirect は呼ばない (1.3.2 参照)

#### 1.3.5 python-xlib のスレッド安全性

python-xlib の `Display` は **同一インスタンスを複数スレッドから同時に使うのは安全ではない** (公式に保証されていない)。Capture の構造上、`read()` を呼ぶスレッドだけが `_display` にアクセスするため、単一スレッド利用の前提は守られる。`close()` を別スレッドから呼ぶ場合に限り Display 操作が並行する可能性があるが、`close()` 側は `_display.close()` 1 回だけなので、`read()` 中の close を呼んだ場合の挙動を docstring で MAY 注意するに留める。

#### 1.3.6 例外モデル (X11)

| 状況                                    | 振る舞い                                                                                                   |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `is_wayland_native()` が True           | `__init__` → `RuntimeError("Capture requires X11 or XWayland; native Wayland is not supported")`           |
| `find_pid() is None`                    | `__init__` → `RuntimeError("VRChat is not running")`                                                       |
| `open_x11_display()` が None            | `__init__` → `RuntimeError("X11 display unavailable")`                                                     |
| `find_vrchat_window() is None`          | `__init__` → `RuntimeError("VRChat top-level window is not yet mapped")` (Display は close してから raise) |
| `composite.query_version()` が `XError` | `__init__` → `RuntimeError("X11 Composite extension not available: ...")`                                  |
| `redirect_window()` が `XError`         | `__init__` → `RuntimeError("Failed to redirect window: ...")`                                              |
| `read()` 中の `XError`                  | `RuntimeError(f"X11 capture failed: {exc}")` (ndarray を返さない)                                          |
| `read()` 中の geometry \<= 0            | `RuntimeError("Window has invalid geometry")`                                                              |
| close 後 `read()`                       | `RuntimeError("Capture is closed")`                                                                        |

______________________________________________________________________

## 2. Screenshot 側の内部設計

### 2.1 全体フロー

`take_screenshot(*, settle_seconds: float = 0.05) -> Screenshot | None` は以下の 5 ステップを順に実行する (MUST 順序厳守):

| ステップ                     | 動作                                                                                                                                                        | None を返す条件                                                                                         |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 1. プラットフォームチェック  | `sys.platform` が `"win32"` / `"linux"` 以外なら `NotImplementedError`。Linux で `is_wayland_native()` が True なら `RuntimeWarning` を出して `None` を返す | Wayland native                                                                                          |
| 2. focus                     | `vrcpilot.window.focus()` を呼ぶ                                                                                                                            | `False` が返ったら `None` (VRChat 未起動 / ウィンドウ未マップ / プラットフォーム失敗、すべてここで吸収) |
| 3. settle                    | `time.sleep(settle_seconds)` で描画安定を待つ                                                                                                               | (失敗経路なし。`settle_seconds < 0` なら `ValueError`)                                                  |
| 4. ウィンドウ矩形取得        | プラットフォーム別ヘルパで `(x, y, w, h)` を取得                                                                                                            | ヘルパが `None` を返す (PID 未取得 / HWND 未取得 / Display 不在 / Window 不在 / XError / Win32Error)    |
| 5. mss grab + メタデータ構築 | mss でその矩形を grab、`datetime.now(timezone.utc)` を grab 直後に取得、`monitor_index` を解決、`Screenshot` を frozen dataclass として構築                 | grab 失敗 (`mss.exception.ScreenShotError` 等) → `None`                                                 |

`settle_seconds` のバリデーション: `< 0` の場合は `ValueError("settle_seconds must be >= 0")` を raise する (MUST)。`0` は allow (skip 相当)。デフォルトの `0.05` (50ms) はプランで合意済み。

### 2.2 ウィンドウ矩形取得 (`_x11` / `_win32` ヘルパ)

両ヘルパは Capture トラックが `_win32.py` / `_x11.py` に追加し、Screenshot トラックはそれを **import するだけ**。

#### 2.2.1 `_x11.get_window_rect(display, window) -> tuple[int, int, int, int] | None`

シグネチャ:

- 引数: `display: Xlib.display.Display`, `window: Xlib.xobject.drawable.Window`
- 戻り値: `(x, y, width, height)` のタプル。スクリーン上絶対座標。失敗時は `None`。

実装方針:

1. `coords = window.translate_coords(display.screen().root, 0, 0)` を呼ぶ。
2. `coords.x` / `coords.y` は **「親 (この場合 root) における window の原点の座標」** ではなく、translate_coords の意味として **「`(0, 0)` を window 座標系から root 座標系に翻訳した結果」** を返す。
3. 過去コミット `77a6422` の `_get_vrchat_rect_x11` では `-int(coords.x)` していた (符号反転)。これは python-xlib の `translate_coords` の戻り値が「逆向き」になるケースがあるため。**現行設計でも符号は反転して `(-int(coords.x), -int(coords.y))` を使う** (MUST)。判断根拠: 過去動作実績のあるロジックを尊重する。実装後に manual シナリオで実際のスクリーン座標と一致するか目視検証 (`tests/e2e/screenshot.py`) すること。
4. `geom = window.get_geometry()` で `width`, `height` を取得。
5. width \<= 0 または height \<= 0 なら `None` を返す。
6. `Xlib.error.XError` を catch して `None` を返す (BadWindow 等)。
7. `(x, y, int(geom.width), int(geom.height))` を返す。

`sys.platform != "linux"` でのガード: 他のヘルパ同様、関数先頭で `if sys.platform != "linux": raise RuntimeError("unreachable")` を入れる (defensive narrow for pyright)。

#### 2.2.2 `_win32.get_window_rect(hwnd) -> tuple[int, int, int, int] | None`

シグネチャ:

- 引数: `hwnd: int`
- 戻り値: `(x, y, width, height)`。スクリーン上絶対座標。失敗時は `None`。

実装方針:

1. `rect = win32gui.GetWindowRect(hwnd)` を呼ぶ。
2. `GetWindowRect` は `(left, top, right, bottom)` を返す。
3. `width = right - left`, `height = bottom - top`。
4. width \<= 0 または height \<= 0 なら `None` を返す。
5. `pywintypes.error` (HWND が消えた等) を catch して `None` を返す。
6. `(left, top, width, height)` を返す。

DPI 仮想化:

- VRChat (Unity ベース) は per-monitor DPI aware として起動するため、`GetWindowRect` は物理ピクセル座標を返す。
- mss も物理ピクセル座標で grab する。
- したがって追加の DPI 調整は **不要** (MUST 何も追加しない)。
- 念のため、もし将来 DPI 不整合が観測された場合は `ctypes.windll.user32.SetProcessDPIAware()` を呼ぶか、`SetThreadDpiAwarenessContext` を使う対応を Open Question として残すが、初期実装では何もしない。

`sys.platform != "win32"` でのガード: 関数先頭で defensive narrow を入れる。

### 2.3 monitor_index 解決

`mss.MSS().monitors` は `[全モニタ合成 dict, 個別1 dict, 個別2 dict, ...]` の list。各 dict は `{"left": int, "top": int, "width": int, "height": int}` のキーを持つ。

#### 2.3.1 アルゴリズム

```
入力: rect = (x, y, w, h), monitors = sct.monitors
中心点 cx, cy = x + w // 2, y + h // 2
for i, mon in enumerate(monitors[1:], start=1):
    left, top = mon["left"], mon["top"]
    right = left + mon["width"]
    bottom = top + mon["height"]
    if left <= cx < right and top <= cy < bottom:
        return i
return 0  # フォールバック: 全モニタ合成
```

採用判断:

- 「中心点を含むモニタ」とすることで、複数モニタにまたがる場合でも 1 個に確定する (MUST)。
- 中心点がどのモニタにも含まれない (= ウィンドウが全画面外、ありえないが防御として) 場合は `0` (= 合成) にフォールバックする (MUST)。
- 候補が複数ある状況は中心点判定により発生しない。

代替案 (面積最大のモニタを選ぶ) は不採用。理由: 計算コストが上がるわりに、中心点が含まれるモニタと一致するケースが大半。

#### 2.3.2 注意点

- mss の monitors は `MSS()` インスタンスごとに `__init__` で読み込む。したがって `take_screenshot` の各呼び出しで `mss.MSS()` (= `mss.mss()`) コンテキストマネージャを開いて使う。長期保持は不要。
- `monitors[0]` (合成) を grab するわけではない。monitor_index は **メタデータとして返すだけ**。実際の grab は rect を直接渡す (下記 2.4)。

### 2.4 mss + numpy 変換

#### 2.4.1 grab の引数形式

mss の `sct.grab` は dict (`{"left": ..., "top": ..., "width": ..., "height": ...}`) または 4-tuple `(left, top, right, bottom)` を受け付ける。**dict 形式を MUST 使う** (型注釈で意図が明確、mss のドキュメント推奨形式)。

```
region = {"left": x, "top": y, "width": w, "height": h}
shot = sct.grab(region)
```

#### 2.4.2 numpy 変換

`shot` は `mss.base.ScreenShot` のサブクラスで、以下の属性を持つ:

- `shot.bgra: bytes` ... BGRA バイト列 (raw)
- `shot.rgb: bytes` ... RGB バイト列 (mss が変換したもの)
- `shot.size: namedtuple(width, height)`

選択肢の比較:

| 経路                                                                             | バイト数 | numpy 変換コスト                  | 推奨       |
| -------------------------------------------------------------------------------- | -------- | --------------------------------- | ---------- |
| `bgra` → `np.frombuffer().reshape(h, w, 4)` → `[..., :3][..., ::-1]` → `.copy()` | 4·H·W    | reshape 0、slice + reverse + copy | 速度最大   |
| `rgb` → `np.frombuffer().reshape(h, w, 3)` → `.copy()`                           | 3·H·W    | reshape 0、copy のみ              | コード簡潔 |

**採用: `rgb` 経路** (MUST)。根拠: 1080p クラスでは copy コストはほぼ同等で、コードが圧倒的に簡潔。Capture 側 (WGC / X11) は BGRA から自前変換が必須だが、Screenshot は mss が `.rgb` を提供してくれるためそれを使う。

実装擬似:

```
arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.size.height, shot.size.width, 3).copy()
```

`.copy()` は MUST。`np.frombuffer` の戻り値は read-only かつバッファ寿命が `shot` に縛られるため、Screenshot dataclass に格納する前に独立した連続バッファに移す。

#### 2.4.3 sct のライフサイクル

```
with mss.mss() as sct:
    region = {...}
    shot = sct.grab(region)
    captured_at = datetime.now(timezone.utc)
    arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(...).copy()
    monitor_index = _resolve_monitor_index(rect, sct.monitors)
return Screenshot(image=arr, x=x, y=y, width=w, height=h, monitor_index=monitor_index, captured_at=captured_at)
```

MUST 順序: grab → captured_at の取得を **grab 直後** で行う (時刻精度のため)。numpy 変換と monitor_index 解決はそのあと。

### 2.5 captured_at

- `datetime.now(timezone.utc)` で取得 (MUST、UTC 固定)。
- frozen dataclass `Screenshot` のフィールド `captured_at: datetime` に格納。
- なぜ UTC: タイムゾーン不定の `datetime.now()` は環境依存で比較困難。UTC 固定なら呼び出し元で `astimezone()` で local 化できる。

### 2.6 Screenshot dataclass

プランで確定済みの形を踏襲:

```
@dataclass(frozen=True)
class Screenshot:
    image: np.ndarray
    x: int
    y: int
    width: int
    height: int
    monitor_index: int
    captured_at: datetime
```

frozen=True は MUST。`np.ndarray` フィールドの hashable 問題: `frozen=True` でも `__hash__` は dataclass デフォルトでは生成されない (eq=True かつ frozen=True で生成されるが、ndarray は `__eq__` の挙動が独特なので衝突する)。**`eq=False` を指定する** (SHOULD): スクリーンショットを set のキーや dict のキーにする用途は想定されないため、等値性は不要と割り切る。

`__post_init__` バリデーション (MAY): `image.ndim == 3 and image.shape[2] == 3 and image.dtype == uint8` を assert する。frozen でも `__post_init__` は呼べる。実装エージェントの判断に委ねるが、実装した場合は test で必ずカバーすること。

______________________________________________________________________

## 3. エラー条件分岐表

| 状況                                     | `Capture.__init__`                                                           | `Capture.read()`                                                  | `Capture.close()`  | `take_screenshot()`                                        |
| ---------------------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------------------- | ------------------ | ---------------------------------------------------------- |
| 未対応 OS (darwin 等)                    | `NotImplementedError`                                                        | n/a                                                               | n/a                | `NotImplementedError`                                      |
| Linux Wayland native                     | `RuntimeError("...native Wayland is not supported")`                         | n/a                                                               | n/a                | `RuntimeWarning` + `None`                                  |
| VRChat 未起動 (`find_pid` None)          | `RuntimeError("VRChat is not running")`                                      | n/a                                                               | n/a                | `None` (focus が False を返す)                             |
| ウィンドウ未マップ (HWND/XWindow None)   | `RuntimeError("VRChat top-level window is not yet mapped")`                  | n/a                                                               | n/a                | `None`                                                     |
| X11 Display unavailable                  | `RuntimeError("X11 display unavailable")`                                    | n/a                                                               | n/a                | `None` (focus が False)                                    |
| X11 Composite extension 不在             | `RuntimeError("X11 Composite extension not available: ...")`                 | n/a                                                               | n/a                | n/a (Screenshot は Composite 不要)                         |
| WGC `start_free_threaded` `OSError`      | `RuntimeError("Failed to start WGC session: ...")`                           | n/a                                                               | n/a                | n/a (Screenshot は WGC 不要)                               |
| X11 BadWindow / XError (init 中)         | `RuntimeError("Failed to redirect window: ...")` (Display は close してから) | n/a                                                               | n/a                | `get_window_rect` が None 返却 → `take_screenshot` が None |
| X11 BadWindow / XError (read 中)         | n/a                                                                          | `RuntimeError("X11 capture failed: ...")`                         | n/a                | n/a                                                        |
| WGC frame timeout                        | n/a                                                                          | `TimeoutError(f"No frame arrived within {self._frame_timeout}s")` | n/a                | n/a (Screenshot は同期)                                    |
| ウィンドウ geometry \<= 0 (read 中、X11) | n/a                                                                          | `RuntimeError("Window has invalid geometry")`                     | n/a                | `_x11.get_window_rect` が None → Screenshot は None        |
| `mss.grab` が `ScreenShotError`          | n/a                                                                          | n/a                                                               | n/a                | `None` (catch して None 返却)                              |
| `Capture.close()` 後の `read()`          | n/a                                                                          | `RuntimeError("Capture is closed")`                               | n/a                | n/a                                                        |
| `Capture.close()` の二重呼び出し         | n/a                                                                          | n/a                                                               | no-op (idempotent) | n/a                                                        |
| `frame_timeout <= 0`                     | `ValueError("frame_timeout must be > 0")`                                    | n/a                                                               | n/a                | n/a                                                        |
| `settle_seconds < 0`                     | n/a                                                                          | n/a                                                               | n/a                | `ValueError("settle_seconds must be >= 0")`                |
| `vrcpilot.window.focus()` が False       | n/a                                                                          | n/a                                                               | n/a                | `None`                                                     |

注: 「n/a」はそのカラムでは発生しえない/該当しないことを示す。

______________________________________________________________________

## 4. テスト設計の指針 (実装エージェント用)

### 4.1 Capture 側 (`tests/test_capture.py`)

**ファイル全体を `class TestCapture:` ベースに作り直す** (MUST)。旧 `class TestTakeScreenshot:` / `class TestTakeScreenshotWin32:` は削除。グルーピング方針は `MEMORY.md` の `feedback_test_organization` (テストは対象ごとに Test クラスでまとめる) に従う。

#### 4.1.1 `_FakeWindowsCapture` の進化

既存の `_FakeWindowsCapture` は「`start_free_threaded().wait()` の中で 1 フレーム fire して終わり」だが、保持型ではテスト側から **任意のタイミングで複数フレームを発火できる** ようにする。

新しい責務:

- `frame_handler` の参照を保持し、テストから `fake.emit_frame(buf, w, h)` を呼べる。
- `emit_frame` は登録された `on_frame_arrived` を直接呼ぶ。フレーム到着のタイミングを制御できる。
- `start_free_threaded` は即座に `_Control` を返す (バックグラウンドスレッドはシミュレートしない、テストは同期的に進める)。
- `_Control.stop()` は呼ばれた回数を `stop_calls` に記録 (既存と同じ)。
- `start_raises: BaseException | None` は維持 (OSError 経路のテスト用)。

擬似的なクラス構造 (シグネチャレベル):

- `class _FakeWindowsCapture:`
  - `def __init__(self, **kwargs) -> None`: kwargs を保存
  - `def event(self, fn) -> fn`: ハンドラ名で振り分けて保持
  - `def start_free_threaded(self) -> _Control`: Control を返す
  - `def emit_frame(self, payload: bytes, width: int, height: int) -> None`: テストが呼ぶ

`_Control`:

- `def stop(self) -> None`: 呼び出し記録
- `def wait(self, timeout=None) -> None`: no-op (保持型では使わない)

テストは `fake.emit_frame(...)` を呼んでから `cap.read()` を呼ぶ。Event ベース実装ならフレーム到着の通知が事前に立っているので即座に取れる。

#### 4.1.2 X11 側のモック

既存パターンを踏襲しつつ、保持型用に調整:

- `mocker.patch("vrcpilot.capture.open_x11_display", return_value=fake_display)` (新ヘルパが導入された場合)
- `mocker.patch("vrcpilot.capture.find_vrchat_window", return_value=fake_window)`
- `mocker.patch("vrcpilot.capture.composite.query_version")`
- `mocker.patch("vrcpilot.capture.composite.redirect_window")`
- `mocker.patch("vrcpilot.capture.composite.name_window_pixmap", return_value=fake_pixmap)`
- `fake_pixmap.get_image.return_value = mocker.Mock(data=bytes(w * h * 4))`
- `fake_window.get_geometry.return_value = mocker.Mock(width=w, height=h)`

#### 4.1.3 カバレッジ項目 (MUST)

| 項目                             | 概要                                                                                                        |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| ライフサイクル正常系 (Win32)     | `Capture()` を with で開いて `read()` を 3 回呼び、すべて `(H, W, 3) uint8 RGB` の ndarray が返ることを確認 |
| ライフサイクル正常系 (X11)       | 同上、X11 ルート                                                                                            |
| 連続 read で最新フレームのみ取得 | `emit_frame(A) → emit_frame(B) → read()` で B が返ることを確認 (latest-only セマンティクス)                 |
| close idempotence                | `close(); close(); close()` で例外を起こさないことを確認                                                    |
| close 後 read                    | `close(); read()` で `RuntimeError("Capture is closed")` を確認                                             |
| `__exit__` で close される       | with を抜けた後に `cap.read()` が `RuntimeError`                                                            |
| `__exit__` が例外を抑制しない    | with 内で raise した例外が外に伝搬することを確認                                                            |
| frame_timeout                    | フレームを emit せずに `read()` を呼んで `TimeoutError` を確認 (Win32)                                      |
| `frame_timeout <= 0`             | `Capture(frame_timeout=0)` で `ValueError`                                                                  |
| プラットフォーム未対応           | `monkeypatch.setattr("vrcpilot.capture.sys.platform", "darwin")` で `NotImplementedError`                   |
| Wayland native (X11)             | `RuntimeError`、warnings は出さない (Capture は raise)                                                      |
| VRChat 未起動 (両 OS)            | `find_pid` を None モック、`__init__` で `RuntimeError`                                                     |
| ウィンドウ未マップ (Win32)       | `find_vrchat_hwnd` を None モック → `RuntimeError`                                                          |
| ウィンドウ未マップ (X11)         | `find_vrchat_window` を None モック → `RuntimeError`                                                        |
| OSError at start (Win32)         | `fake.start_raises = OSError(...)` → `RuntimeError` (元例外チェイン確認)                                    |
| Composite XError (X11)           | `query_version` で XError → `RuntimeError`                                                                  |
| WGC 設定パラメータ               | `last_kwargs == {"cursor_capture": False, "draw_border": False, "window_hwnd": ...}`                        |

#### 4.1.4 `tests/e2e/capture.py` (新規)

- `Capture` を with で開き、ループで 30 フレーム取得 (約 1 秒分相当、`time.sleep(0.033)` で 30fps を模擬)
- 最初と最後のフレームを `_e2e_artifacts/` に PNG 保存 (numpy → PIL Image 変換、`Image.fromarray(arr)`)
- フレーム間隔の最大・最小・平均を log
- `_helpers.run_scenario` で wrap

### 4.2 Screenshot 側 (`tests/test_screenshot.py`)

#### 4.2.1 モック方針

- `mocker.patch("vrcpilot.screenshot.mss.mss")` で `MSS` インスタンスを差し替え。`sct.grab` の戻り値はフィクスチャから流す (`shot.rgb = bytes(w*h*3)`, `shot.size = mocker.Mock(width=w, height=h)`)。
- `mocker.patch("vrcpilot.screenshot.focus", return_value=True)` で focus を制御。
- `mocker.patch("vrcpilot.screenshot.time.sleep")` で settle を no-op 化 (テストを高速に)。
- プラットフォーム別に `mocker.patch("vrcpilot.screenshot._x11.get_window_rect", return_value=(100, 200, 800, 600))` (Linux) または `mocker.patch("vrcpilot.screenshot._win32.get_window_rect", return_value=(100, 200, 800, 600))` (Windows) で矩形ヘルパを置き換え。
- `find_pid` / `find_vrchat_hwnd` / `find_vrchat_window` などはヘルパ内に隠蔽されているので、Screenshot のテストでは矩形ヘルパ自体をモックすれば十分。

#### 4.2.2 monitors のモック

```
fake_monitors = [
    {"left": 0, "top": 0, "width": 3840, "height": 1080},  # 合成
    {"left": 0, "top": 0, "width": 1920, "height": 1080},  # 左モニタ
    {"left": 1920, "top": 0, "width": 1920, "height": 1080},  # 右モニタ
]
fake_sct.monitors = fake_monitors
```

フィクスチャとして `tests/conftest.py` に置くか、テスト内に書くかは実装エージェントの判断。複数テストで共有するなら fixture 化推奨。

#### 4.2.3 カバレッジ項目 (MUST)

| 項目                            | 概要                                                                                                                                                         |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 正常系メタデータ                | `image.shape == (h, w, 3) and dtype == uint8`, `x/y/width/height` が rect ヘルパ戻り値と一致, `captured_at.tzinfo is timezone.utc`, `monitor_index` が期待値 |
| focus 失敗時 None               | `focus` を False モック → `take_screenshot()` が `None`                                                                                                      |
| Wayland native                  | `is_wayland_native` を True モック (Linux) → warnings + `None`                                                                                               |
| 矩形ヘルパが None               | `get_window_rect` を None モック → `None`                                                                                                                    |
| `mss.grab` が `ScreenShotError` | `sct.grab.side_effect = ScreenShotError(...)` → `None`                                                                                                       |
| プラットフォーム未対応          | `sys.platform = "darwin"` → `NotImplementedError`                                                                                                            |
| settle が呼ばれる               | `time.sleep` のモックが `settle_seconds=0.05` で呼ばれた assertion                                                                                           |
| settle_seconds の伝搬           | `take_screenshot(settle_seconds=0.5)` で sleep が 0.5 秒で呼ばれる                                                                                           |
| `settle_seconds < 0`            | `ValueError`                                                                                                                                                 |
| monitor_index: 左モニタ         | rect 中心が左モニタ範囲 → 1                                                                                                                                  |
| monitor_index: 右モニタ         | rect 中心が右モニタ範囲 → 2                                                                                                                                  |
| monitor_index: 画面外           | rect 中心がどのモニタにも入らない → 0 (合成にフォールバック)                                                                                                 |
| frozen                          | `Screenshot(...).x = 999` で `FrozenInstanceError`                                                                                                           |
| 順序保証                        | focus → sleep → grab の順で呼ばれることを `mocker.call_order` 系で確認 (SHOULD、最低限 focus が grab より前を確認)                                           |

#### 4.2.4 `tests/e2e/screenshot.py` の更新

既存ファイルを新 API に書き換える:

- `vrcpilot.take_screenshot()` の戻りが `Screenshot` になるので、`shot.image` (ndarray) を PIL Image に変換して PNG 保存
- メタデータ (`x`, `y`, `width`, `height`, `monitor_index`, `captured_at`) を log 出力
- assertion: `shot.x >= 0`, `shot.y >= 0`, `shot.width > 0`, `shot.height > 0`, `0 <= shot.monitor_index <= len(monitors)-1` (monitors の取得は mss を別途使う or skip)
- 過去の cp932 制約により、log メッセージは ASCII で書く (em-dash や → を使わない)

______________________________________________________________________

## 5. 実装エージェント間の責任境界 (並列衝突回避)

### 5.1 ファイル単位の所有権

| ファイル                     | Capture トラック                                                        | Screenshot トラック                          |
| ---------------------------- | ----------------------------------------------------------------------- | -------------------------------------------- |
| `src/vrcpilot/capture.py`    | 全面書き換え (所有)                                                     | 触らない                                     |
| `src/vrcpilot/screenshot.py` | 触らない                                                                | 新規作成 (所有)                              |
| `src/vrcpilot/_win32.py`     | `get_window_rect` 追加 (所有)                                           | import するのみ                              |
| `src/vrcpilot/_x11.py`       | `get_window_rect` 追加 + (案 A 採用なら) `open_x11_display` 追加 (所有) | import するのみ                              |
| `src/vrcpilot/__init__.py`   | (ジョイント部)                                                          | (ジョイント部)                               |
| `src/vrcpilot/cli.py`        | 触らない                                                                | `_run_screenshot` 書き換え (所有)            |
| `tests/test_capture.py`      | 全面書き換え (所有)                                                     | 触らない                                     |
| `tests/test_screenshot.py`   | 触らない                                                                | 新規作成 (所有)                              |
| `tests/e2e/capture.py`       | 新規作成 (所有)                                                         | 触らない                                     |
| `tests/e2e/screenshot.py`    | 触らない                                                                | 書き換え (所有)                              |
| `pyproject.toml`             | (ジョイント部)                                                          | (ジョイント部、`mss` / `numpy` の prod 昇格) |

### 5.2 ジョイント部の調整

`pyproject.toml`、`src/vrcpilot/__init__.py` は両トラックが触る可能性があるため、**プラン本体に従い Screenshot トラックがまとめて担当する** (MUST)。Capture トラックは:

- `src/vrcpilot/__init__.py` の `__all__` への `Capture` 追加と import 文追加だけ Screenshot トラックに依頼するか、または Capture トラックが Phase 2 の冒頭で先に書いて Screenshot トラックは差分マージする
- 実用上は **Capture トラックが先にコミット** (`feat(_win32, _x11): ...`、`feat(capture): ...`) を済ませ、Screenshot トラックは Capture トラック完了後に branch を rebase してから作業を始めるのが安全

ブランチ運用: 両トラックは共通ブランチ `feature/20260429/capture-and-screenshot` の上で順次コミットする (CLAUDE.md の git 運用に従う)。並列実装は**ローカル作業の並列化**であり、コミット順序は直列 (依存関係を尊重)。

### 5.3 矩形ヘルパの API 確定 (両トラック共通の合意)

Capture トラックが追加する `_x11.get_window_rect` / `_win32.get_window_rect` の API は本書 2.2 で確定済み。Screenshot トラックはこの API を期待値として実装してよい。実装後の API 変更が必要になったら **Capture トラックが Screenshot トラックに通知すること** (SHOULD、エージェント間連絡)。

### 5.4 共通 import の前提

- numpy は両モジュールが import する。`pyproject.toml` の prod 依存追加は Screenshot トラックが担当 (5.2)。Capture トラックは pyproject に触る前提で実装してよいが、実際の `pyproject.toml` 編集はしない。
- `mss` は Screenshot のみが import。Capture は import しない (Capture は WGC / X11 Composite 直接、mss は使わない)。
- Capture トラックが追加する `numpy.ndarray` 戻り値の型注釈と Screenshot dataclass の `image: np.ndarray` フィールドは、numpy が prod 依存になっているという前提を共有する。

______________________________________________________________________

## 実装エージェントへの引き継ぎ事項

### Capture トラック チェックリスト

01. ブランチ `feature/20260429/capture-and-screenshot` を `main` から分岐していることを確認する。
02. `src/vrcpilot/_win32.py` に `get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None` を本書 2.2.2 の仕様で追加する。`pywintypes.error` を catch し、width/height \<= 0 の場合 None を返すこと。
03. `src/vrcpilot/_x11.py` に `get_window_rect(display, window) -> tuple[int, int, int, int] | None` を本書 2.2.1 の仕様で追加する。`translate_coords` の戻り値の符号反転 (`-int(coords.x)`) を忘れないこと。
04. `src/vrcpilot/_x11.py` に `open_x11_display() -> Xlib.display.Display | None` を追加する (案 A 採用)。失敗時は既存 `x11_display` と同じ例外群を catch して None を返す。
05. `src/vrcpilot/capture.py` から `take_screenshot` / `_take_screenshot_win32` / `_take_screenshot_x11` を削除し、`Capture` クラスを本書 1.1-1.3 の仕様で実装する。`PIL.Image` の import は削除する。
06. WGC 側は単一スロット + `threading.Event` 方式 (本書 1.2.1) で実装する。`on_frame_arrived` 内で BGRA → RGB へ変換し、`.copy()` で連続化してからスロットに格納する。`control.stop()` を `on_frame_arrived` 内で呼ばないこと。
07. X11 側は `__init__` で Display 接続と redirect を確立し、`read()` のたびに `name_window_pixmap` → `get_image` → `pixmap.free()` を実行する (本書 1.3.2)。unredirect は呼ばない。
08. `close()` の冪等性、`__exit__` の例外非抑制、close 後 `read()` の `RuntimeError` を MUST 実装する。
09. `tests/test_capture.py` を `class TestCapture:` 構造で全面書き直し、本書 4.1.3 のカバレッジ項目をすべてカバーする。`_FakeWindowsCapture` を `emit_frame` ベースに進化させる。
10. `tests/e2e/capture.py` を新規作成 (本書 4.1.4)。30 フレーム取得 + 最初・最後の PNG 保存。
11. コミット前に `just run` がすべてパスすることを確認する。コミットは `feat(_win32, _x11): ウィンドウ矩形取得ヘルパを追加` → `feat(capture): Capture クラスで連続フレーム取得を提供` の 2 段階で行う。

### Screenshot トラック チェックリスト

01. ブランチ `feature/20260429/capture-and-screenshot` 上で、Capture トラックの矩形ヘルパコミットが入った後の HEAD から作業する (rebase または fast-forward)。
02. `pyproject.toml` の `[project.dependencies]` に `mss>=10.2.0` と `numpy>=2.1` を追加し、`[dependency-groups].dev` から `mss` を削除して `uv lock` を更新する。
03. `src/vrcpilot/screenshot.py` を新規作成し、`Screenshot` frozen dataclass と `take_screenshot(*, settle_seconds: float = 0.05) -> Screenshot | None` を本書 2.1-2.6 の仕様で実装する。`Screenshot` は `eq=False` で frozen=True とする (numpy 配列の等値性問題を回避)。
04. プラットフォーム判定 → Wayland native warning → focus → sleep → 矩形ヘルパ → mss grab → captured_at → numpy 変換 → monitor_index 解決 → Screenshot 構築の順序を MUST 守る。
05. 矩形ヘルパは Capture トラックが追加した `_x11.get_window_rect` / `_win32.get_window_rect` を import するのみ。新しい矩形ロジックを書かない。
06. monitor_index は中心点判定で 1 個に確定し、画面外の場合は 0 にフォールバックする (本書 2.3.1)。
07. mss `.rgb` 経路で numpy 変換し、`.copy()` で連続化する (本書 2.4.2)。`captured_at` は grab 直後に `datetime.now(timezone.utc)` で取得する。
08. `src/vrcpilot/__init__.py` の `__all__` に `Capture`, `Screenshot`, `take_screenshot` を追加し、import 文を追加する (Capture トラックの成果物を import に含めること)。
09. `src/vrcpilot/cli.py` の `_run_screenshot` を新 API に書き換える: `Screenshot.image` (ndarray) を PIL Image に変換 (`Image.fromarray(arr)`) → PNG 保存。
10. `tests/test_screenshot.py` を新規作成し、本書 4.2.3 のカバレッジ項目をすべてカバーする。`mss.mss` / `vrcpilot.window.focus` / `time.sleep` をモックする。
11. `tests/e2e/screenshot.py` を新 API に書き換える (本書 4.2.4)。メタデータ assertion と PNG 保存を含む。log 出力は cp932 互換の ASCII のみ使用。
12. コミット前に `just run` がすべてパスすることを確認する。コミットは `chore(deps): mss と numpy を production 依存に昇格` → `feat(screenshot): take_screenshot を Screenshot メタデータ付き API に置き換え` → `refactor(__init__, cli): Capture / Screenshot を公開 API に追加し CLI を新型に対応` → `test(manual): screenshot manual シナリオを Screenshot API へ更新` の 4 段階で行う。
