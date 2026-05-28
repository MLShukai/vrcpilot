---
name: screenshot-mss-removal
description: take_screenshot を mss から Capture へ移行した仕様の確定事項 (monitor_index 廃止メカニズム / 座標系不変条件 / subclass trap)
metadata:
  type: project
---

`take_screenshot` を `mss` 領域 grab から `vrcpilot.capture.Capture`
(ウィンドウ内容キャプチャ) へ移行する仕様を策定 (2026-05-29、承認済み方針)。
仕様書は `/tmp/vrcpilot-mss-spec.md` に出力。確定した設計判断:

**新シグネチャ**: `def take_screenshot(*, pid: int | None = None) -> Screenshot | None`。
`focus()` 呼び出しと `settle_seconds` 引数を撤廃 (唯一の意図的な振る舞い変更)。

**座標系の不変条件 (最重要)**: `Capture` と `get_vrchat_window_rect` は同じ
finder で同じウィンドウを解決するので image-(0,0) == window-local-(0,0)。
`Screenshot.width/height` は **キャプチャ画像由来** (`shape[1]`/`shape[0]`)、
`x/y` は rect 由来 (informational)。これで `image.shape == (height, width, 3)`
が無条件成立。rect の width/height は使わない。

**subclass trap**: `VRChatMultipleInstancesError` は `VRChatNotRunningError`
のサブクラス (`process/errors.py`)。`take_screenshot` で pid を自前 resolve
すると多重起動エラーを握り潰す。**pid をそのまま `get_vrchat_window_rect` →
`Capture` に渡し** not-running/multi-instance のセマンティクスを
`get_vrchat_window_rect` に委譲する (これが既に None変換 / re-raise を正しく
やっている)。多重起動は伝搬、未起動は None。

**例外マッピング**: `with Capture(pid=pid) as cap: image = cap.read()` を
`except (RuntimeError, TimeoutError): return None` で囲む。
`NotImplementedError` は伝搬。

**monitor_index 廃止メカニズム (確定: 候補 A)**: `@dataclass(frozen=True, eq=False)`
の `Screenshot` に `__post_init__` を追加し、`monitor_index != 0` の時だけ
`DeprecationWarning` ("monitor_index" + "0.6.0" を含む) を発する。

- 採用理由: `take_screenshot` は常に 0 を設定 → `save()` / `cli/ocr.py` /
  `cli/detect.py` の通常パイプラインは無警告。属性アクセスごとに警告する候補 B
  (`__getattribute__` + `object.__getattribute__` bypass) は save() 内 bypass を
  全箇所要求し脆い。プロパティ候補 C は frozen dataclass で同名フィールドと
  共存不可。
- フィールド/kwarg/YAML キー/位置は全て不変 (0.5.x 契約保持、0.6.0 で削除予告)。

**テスト戦略の罠**: `pyproject.toml` に `filterwarnings = ["ignore::DeprecationWarning"]`
があるため、非ゼロ monitor_index で構築する既存テスト (save/load round-trip 等、
`_make_screenshot` のデフォルトは `monitor_index=1`) は警告が無視され green の
まま。**`pytest.warns` で包んではならない**。警告を検証するテストだけ
`pytest.warns(DeprecationWarning, match="0.6.0")` で明示的に包む。

**mss 除去の全 inventory**: `screenshot.py` / `controls/mouse/linux.py` /
`tests/e2e/_helpers.py` / `pyproject.toml`+`uv.lock`。

- `mouse/linux.py`: `mss.MSS().monitors[0]` を `open_x11_display()` +
  `display.screen().width_in_pixels/height_in_pixels` に置換、None で
  `RuntimeError` (例外型が XError→RuntimeError に変わる、mouse テストの skip 文言
  更新要)。Display は caller が close する責務。
- `e2e/_helpers.py`: `mss` デスクトップ grab を `import pyscreenshot as ImageGrab; ImageGrab.grab().save(path)` に。`pyscreenshot` は dev グループ (prod ではない、
  e2e 補助コード専用)。
- `windows.py` / `controls/mouse/windows.py` の `mss` は docstring の言及だけ
  (依存ではない) なので **触らない**。
- `cli/ocr.py` / `cli/detect.py` は `shot.monitor_index` を読むだけで monitor_index==0
  だから無警告、**コード変更不要**。

関連: \[\[capture-screenshot-internal-design\]\] (前身の Capture/Screenshot 分割仕様)。
