---
name: pid-speaker-routing-relay
description: vrcpilot.speaker.routing と CLI speaker を PID 単位 capture → soundcard リレー方式に書き換えるための確定仕様 (cross-platform)
metadata:
  type: project
---

# Spec: PID 単位 VRChat 音声リレー (speaker.routing + CLI speaker)

承認済みプラン [`C:\Users\22shi\.claude\plans\claude-pid-speaker-windows-windows-only-cheeky-puppy.md`](../../../.claude/plans/claude-pid-speaker-windows-windows-only-cheeky-puppy.md) を仕様レベルまで分解した版。Phase 2 の 4 並列実装 (実装 A/B、テスト C/D) はこの文書だけで担当領域が決定できることを目標とする。

旧仕様 `pid_speaker_routing_windows.md` (IAudioPolicyConfig ベース) は廃止。

## 1. 概要 (Overview)

### 解決する問題

- VRChat を複数 PID 同時起動 (multi-instance) した際、各インスタンスの出力音声を別々のスピーカーデバイスへ分離して扱いたい。
- 旧 `IAudioPolicyConfig` 方式は VRChat の `start_protected_game.exe` 経由起動 + 同一 exe の多重起動という制約により per-PID 分離を保証できず、放棄。
- 既に動いている **PID 単位のキャプチャ** (Windows: proc-tap、Linux: PipeWire native、48 kHz / stereo / float32) を、ユーザー空間で `soundcard` の出力デバイスへ転送 (リレー) すれば、OS policy に依存せず per-PID 分離が成り立つ。

### ゴール

- `vrcpilot.speaker.routing` 公開 API として `AudioDevice` / `list_devices` / `default_device` / `find_device` / `Router` / `route` / `AudioRoutingError` / `DeviceNotFoundError` を提供する。
- CLI `vrcpilot speaker` を `list` / `route` の 2 サブコマンドに刷新する (`get` / `set` / `reset` は削除)。
- Windows と Linux のどちらでも、platform 別ファイルなしの **cross-platform 一本** で動作させる。
- 既定 `chunk_seconds = 0.02` (20 ms) で低レイテンシ重視。underrun が出る環境向けに調整余地を残す。

### 非ゴール (Out of Scope)

- macOS / FreeBSD など Win / Linux 以外への対応。`Speaker` の platform ガードと同じく `NotImplementedError` で fail-fast。
- 1 コマンドで複数 (PID, device) ペアを扱う `route-many` 等の拡張。v2 以降。
- 音量 / ミックス / イコライザ等の DSP 機能。素のフレーム転送のみ。
- VRChat 以外のプロセス音声の routing。`Speaker` の PID-scoped 制約をそのまま継承する。
- daemon / バックグラウンド常駐モード。foreground プロセス + Ctrl+C 停止のみ。
- 音声フォーマット変換。常に `SAMPLE_RATE` (48 kHz) / `CHANNELS` (2 ch) / float32 を soundcard.Player にそのまま渡す。

## 2. 用語定義 (Glossary)

- **リレー (relay)**: vrcpilot 内部の `Speaker` (PID-scoped capture) が読んだフレームを、`soundcard.Speaker.player()` (出力ストリーム) にそのまま転送する経路。
- **出力デバイス / スピーカー (output device / speaker)**: OS が認識する物理 / 仮想の音声出力エンドポイント。`soundcard.all_speakers()` で列挙される単位と一致。
- **system default**: OS の既定出力スピーカー。`soundcard.default_speaker()` 相当。
- **chunk_seconds**: `SpeakerLoop` が `Speaker.read()` の間に挟む sleep 秒数 (キャプチャ側レイテンシのスループット単位)。
- **blocksize**: `soundcard.Speaker.player(blocksize=...)` に渡す出力バッファのフレーム数 (出力側レイテンシ単位)。
- **AudioDevice**: 公開 dataclass。`soundcard` の Speaker 内部表現に依らない、vrcpilot 公開 API の デバイス記述。
- **解決後のデバイス (resolved device)**: `Router.__init__` で `device` 引数 (`None` / `str` / `AudioDevice`) を一意な `AudioDevice` まで解決した結果。
- **PID-scoped capture**: VRChat の特定 PID の出力音声のみを抽出する既存仕組み (`vrcpilot.speaker.Speaker` / `SpeakerLoop`)。

## 3. 要求仕様 (Requirements)

### 3.1 機能要件 (Functional Requirements)

各要件はテスト可能な粒度。MUST = テストで検証する必須挙動、SHOULD = 推奨だが境界での例外あり、MAY = 任意。

#### F1. デバイス列挙

- F1.1 `list_devices() -> list[AudioDevice]` MUST すべての利用可能な出力スピーカーデバイスを返す。
- F1.2 返却順序 MUST: (a) `is_default == True` のものが先頭、(b) その後 `name` 昇順 (Python 既定の文字列比較 — Unicode codepoint 順、大文字小文字を区別する)。
- F1.3 `is_default == True` のデバイスは 0 個か 1 個。0 個になるのは OS に出力デバイスが 1 つも存在しない場合のみ。
- F1.4 出力デバイスが 1 つも存在しない場合、`list_devices()` は空リスト `[]` を返す (例外を上げない)。
- F1.5 `default_device() -> AudioDevice` MUST OS 既定出力スピーカーを返す。出力デバイスが存在しない場合は `DeviceNotFoundError` を上げる。
- F1.6 `find_device(query: str) -> AudioDevice` MUST 以下の 3 段階で解決する:
  1. `query == device.id` の完全一致を全列挙から探す。1 件ヒットなら確定。
  2. 1 で 0 件なら `query == device.name` の完全一致 (大文字小文字を区別する) を探す。1 件ヒットなら確定。
  3. 2 で 0 件なら `query.lower() in device.name.lower()` の部分一致を全列挙から探す。
- F1.7 F1.6 の各段で **2 件以上ヒットしたら即 `AudioRoutingError`** (次の段にフォールスルーしない)。例外メッセージはヒットしたデバイス名 / id を全件列挙する (§9 参照)。
- F1.8 F1.6 の 3 段全てで 0 件なら `DeviceNotFoundError`。例外メッセージは全出力デバイスの id / name を列挙する (§9 参照)。
- F1.9 `find_device("")` は仕様上「部分一致が全件にマッチ」となるため、出力デバイスが 2 つ以上なら `AudioRoutingError`、1 つだけならそれを返す、0 個なら `DeviceNotFoundError`。空文字を渡す CLI 経路は無いので想定外入力扱いで OK。

#### F2. Router ライフサイクル

- F2.1 `Router(pid, device=None, *, chunk_seconds=0.02, blocksize=None)` のコンストラクタは以下を MUST:
  - `device` を `AudioDevice` まで解決する (`None` → `default_device()` / `str` → `find_device(query)` / `AudioDevice` → そのまま)。
  - `chunk_seconds` を保持する (検証は `SpeakerLoop` に委譲、`<= 0` は `SpeakerLoop.__init__` が `ValueError` を上げる)。
  - `blocksize` を保持する。
  - キャプチャ / 出力ストリームは **まだ開かない**。`start()` で開く。
- F2.2 `Router.start()` MUST:
  - キャプチャ側: `SpeakerLoop(callback=self._on_frames, chunk_seconds=self._chunk_seconds, pid=self._pid)` を生成し `start()` する。
  - 出力側: 解決済みデバイスから `soundcard.Speaker.player(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=self._blocksize)` でコンテキストマネージャを取得し `__enter__` で開く。
  - 順序: 出力ストリームを先に開いてから `SpeakerLoop.start()` を呼ぶ。これにより、最初のコールバックが届いた時点で player は既に再生可能。
  - 失敗時のロールバック: `SpeakerLoop` 生成 / start で例外が出たら、既に開いた player を `__exit__(None, None, None)` でクリーンアップしてから例外を再 raise。
- F2.3 既に `start()` 済みの状態で再度 `start()` を呼んだ場合 MUST 二重起動を**しない** (no-op として何もせず正常 return)。
- F2.4 `Router.stop()` MUST 既存の `SpeakerLoop.stop()` を呼んでから player の `__exit__(None, None, None)` を呼ぶ。SpeakerLoop の `stop()` が例外を上げても player の cleanup は MUST 実行する (`try / finally`)。
- F2.5 `stop()` を未開始状態または停止済み状態で呼んでも MUST 例外を上げない (no-op)。
- F2.6 `Router.close()` MUST `stop()` の別名として振る舞う (Router 自体は持続するリソースを `start()` 以前には保持しないため、`stop()` 後の再 `start()` を許す)。
  - 補足: `close()` 後に `start()` 可能かは F2.13 で規定する。
- F2.7 コンテキストマネージャ: `__enter__` MUST `self.start()` を呼んで `self` を返す。`__exit__` MUST `self.stop()` を呼び、例外は伝播させる (swallow しない)。
- F2.8 `is_running` プロパティ MUST 「`start()` 後かつ `stop()` 前」の期間 True を返す。具体的には内部 `SpeakerLoop` の `is_running` (worker thread の生存) と一致する。
- F2.9 `device` プロパティ MUST `__init__` で解決された `AudioDevice` を返す。`start()` 前後で同じ値。
- F2.10 フレーム転送経路 (`_on_frames`): `SpeakerLoop` から渡される ndarray を player に転送する。MUST:
  - 空フレーム (`frames.size == 0`) は **何もせず return** (silence tick の skip)。
  - 非空フレームは `player.play(frames)` に渡す。player が `None` の場合 (= まだ start していない / 既に stop した) は何もせず return (race condition 防衛)。
- F2.11 VRChat プロセス死亡時の挙動 MUST: `SpeakerLoop` の worker thread が例外をキャプチャするため、`Router.stop()` を呼んだ時点で `SpeakerLoop.stop()` がその例外を再 raise する。`Router` は `stop()` 内で `try / finally` を使い、player cleanup を実行した**後**に SpeakerLoop の例外を伝播する。
- F2.12 二重 `stop()` 安全性 MUST: 1 回目の `stop()` が `SpeakerLoop` 例外を再 raise した後、2 回目の `stop()` は例外なしで no-op として戻る (`SpeakerLoop.stop()` 自体が exception を clear する仕様に依存)。
- F2.13 `stop()` 後の `start()` 再呼び出し: MUST 新しい `SpeakerLoop` と新しい player を作って再開する (`SpeakerLoop` 自体は close 後の再 start を許さないが、Router は内部で新しいインスタンスを生成して回避する)。これによりコンテキストマネージャを複数回入れ直す使い方を許可する。

#### F3. route ヘルパ

- F3.1 `route(pid, device=None, *, chunk_seconds=0.02, blocksize=None) -> Router` MUST `Router` を構築し `start()` を呼んで返す。呼び出し側がライフサイクル (`stop()` / `close()` / `with`) を所有する。
- F3.2 `start()` で例外が出た場合は MUST Router オブジェクトを返さず例外を伝播する。

#### F4. 例外階層

- F4.1 `AudioRoutingError(RuntimeError)` MUST: `routing` モジュールが定義する全例外の基底。
- F4.2 `DeviceNotFoundError(AudioRoutingError)` MUST: デバイス解決でゼロヒットになった場合の専用例外。
- F4.3 公開 API から伝播しうるその他の例外: `ValueError` (`chunk_seconds <= 0`)、`ImportError` (`soundcard` 未インストール)、`OSError` (`soundcard` の dlopen 失敗、libpulse 等)、`RuntimeError` (`SpeakerLoop` / `Speaker` 由来の runtime 失敗、VRChat 未起動など)、`NotImplementedError` (Win/Linux 以外のプラットフォーム — `Speaker` 由来)、`VRChatMultipleInstancesError` (`pid` が None かつ多重起動の場合 — `Speaker` 由来だが本 API では `pid` 必須化で実質発生しない、後述)。
- F4.4 `Router.__init__(pid, ...)` の `pid` MUST `int` 型 (省略不可)。これは「multi-instance を扱う前提で明示する」設計判断 (CLI 仕様 §4 と整合)。Python は型注釈強制しないので runtime チェックは行わないが、`None` を渡せば下流の `Speaker(pid=None)` 経由で `resolve_pid` が呼ばれ、多重起動時は `VRChatMultipleInstancesError` が伝播する。仕様上は「`pid` は int を渡すべき」と書くに留める。

#### F5. CLI `speaker list`

- F5.1 引数: なし (positional / option いずれも追加しない)。
- F5.2 stdout に YAML を出力 MUST。スキーマは §4.1 で規定。
- F5.3 終了コード MUST: 成功 0、`OSError` / `ImportError` 等で 1。

#### F6. CLI `speaker route`

- F6.1 引数:
  - `--pid PID` (`int`, 必須): リレー対象 VRChat PID。argparse の `required=True` で強制。
  - `--device QUERY` (`str`, 省略可): 解決クエリ。省略時は `default_device()`。
  - `--chunk-seconds FLOAT` (`float`, 省略可、既定 `0.02`): SpeakerLoop の chunk 秒数。
  - `--blocksize N` (`int`, 省略可、既定 `None`): soundcard player のブロックサイズ。
- F6.2 `--pid` 必須化により、`add_pid_arg` (`required=False`) は **使わない**。`speaker` 専用に `parser.add_argument("--pid", type=int, required=True, ...)` を直接書く。
- F6.3 起動時の stderr 出力 MUST: route 開始時に 1 行のサマリを stderr に書く (§4.2 で書式規定)。`--device` 未指定時は末尾に ` (system default)` を付ける。
- F6.4 foreground 動作 MUST: `Router` を `with` で開いた状態で停止シグナルを待つ。停止シグナルは:
  - `KeyboardInterrupt` (Ctrl+C / SIGINT): 正常終了経路。`with` を抜けて exit code 0。
  - SpeakerLoop 内例外 (VRChat 死亡など): `Router.stop()` で再 raise → CLI で捕捉して exit code 1。
- F6.5 待機ループ MUST: busy loop ではなく `time.sleep` ベースで CPU を消費しない (例: `time.sleep(0.5)` を `KeyboardInterrupt` まで繰り返す)。`signal.pause` は Windows で使えないので使わない。
- F6.6 終了コード MUST: §4.3 のテーブルに従う。

#### F7. 既存仕様との整合

- F7.1 `vrcpilot.speaker.routing` パッケージは既存 `speaker/` の同階層に新規作成する。`speaker/__init__.py` の `__all__` は変更しない (routing は名前空間越しに公開、`speaker.routing` として import)。
- F7.2 CLI ディスパッチ ([`src/vrcpilot/cli/__init__.py`](../../src/vrcpilot/cli/__init__.py)) の `_COMMANDS` に `"speaker": speaker` を追加 MUST。`mic` の後・`mouse` の前あたり、help の並び順を意識して挿入する (推奨: `mic` の直後)。
- F7.3 `pyproject.toml`: 新規依存追加なし。`comtypes` を削除する MUST (旧 IAudioPolicyConfig 用、本仕様では未使用)。`uv lock` を再生成 MUST。
- F7.4 Windows / Linux 以外のプラットフォームで `import vrcpilot.speaker.routing` 自体は失敗させない (cross-platform モジュール、`Speaker` 経由で初めて `NotImplementedError` が出る)。`list_devices` / `default_device` は soundcard が動けば動く (macOS でも soundcard は一応動く) が、本仕様のサポートプラットフォームではない。

### 3.2 非機能要件 (Non-Functional Requirements)

| ID  | 区分         | 要件                                                                                                                                                                                                                                                                                                                              |
| --- | ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NF1 | レイテンシ   | 既定設定 (`chunk_seconds=0.02`, `blocksize=None`) で、capture → output 経路の総追加レイテンシは SHOULD 100 ms 以下 (実機での測定は Phase 6 で実施、目安値の妥当性は docs/virtual-audio.md に追記)。                                                                                                                               |
| NF2 | スループット | キャプチャの 48 kHz / stereo / float32 を underrun なしで連続的に転送できる。長時間 (15 分以上) 連続動作で memory leak / GC pause 起因の中断がないこと。                                                                                                                                                                          |
| NF3 | リソース解放 | `Router` ライフサイクル終了時、PipeWire stream / proc-tap session / soundcard player の全てが MUST 解放される (leak ゼロ)。leak は `Speaker.close()` / `SpeakerLoop.close()` / soundcard player の `__exit__` の組み合わせで保証。                                                                                                |
| NF4 | エラー観測性 | CLI からの異常終了は MUST stderr に `vrcpilot: <message>` 形式の 1 行を出力する (既存 CLI 規約と整合)。例外の stack trace は MAY 表示しない (整然とした UX 優先)。`--debug` 等の verbosity フラグは導入しない (既存規約と同じ — print のみ)。                                                                                     |
| NF5 | 型           | 公開 API の全シグネチャは pyright strict で型エラーなし。`soundcard` は型スタブが無いので `# pyright: ignore[reportUnknownMemberType, reportMissingTypeStubs]` を内部実装側で局所的に許容 (`mic/devices.py` 既存パターンと同じ)。公開 API には Any を漏らさない。                                                                 |
| NF6 | 互換性       | Python 3.12 / 3.13 / 3.14 × Win / Linux の既存 CI マトリクスで動作する。doctest は本パッケージでは追加しない (`--doctest-modules` 設定下では doctest が走るが、検出対象は docstring 内の `>>>` 例のみ — 本仕様では `>>>` 例を書かない方針)。                                                                                      |
| NF7 | 依存         | 新規 dependency なし。`soundcard` (既存 dep)、`numpy` (既存 dep)、`pyyaml` (既存 dep)、`argcomplete` (既存 dep) のみ使用。`comtypes` (旧仕様用) を pyproject.toml から削除 MUST。                                                                                                                                                 |
| NF8 | テスト       | §6 で別途規定。                                                                                                                                                                                                                                                                                                                   |
| NF9 | 並行性       | `Router` の状態遷移 (`start` / `stop` / `_on_frames`) は SpeakerLoop の worker thread と main thread 間で起こる。MUST: `start` / `stop` を main thread から呼ぶ前提とし、`_on_frames` のみ worker thread から呼ばれる。`_on_frames` は `self._player` のスナップショットを読むだけにする (None 比較で抜ける) ため、ロックは不要。 |

## 4. インターフェース仕様 (Interfaces / Contracts)

### 4.1 Python 公開 API (`vrcpilot.speaker.routing`)

`vrcpilot.speaker.routing.__init__.py` で以下を公開し `__all__` に含める:

#### AudioDevice

説明: 出力スピーカーの不変記述。
定義: `@dataclass(frozen=True, slots=True)` の dataclass。
フィールド:

- `id: str` — soundcard の Speaker `_id` (Windows は GUID 形式、Linux は PipeWire の node 識別子に依存)。
- `name: str` — ユーザー向け表示名 (FriendlyName)。
- `is_default: bool` — OS の既定出力スピーカーなら True。

不変条件:

- frozen=True により再代入不可。
- 同一インスタンス内で `is_default == True` のものは `list_devices()` の出力中で最大 1 個。

#### list_devices

シグネチャ: `def list_devices() -> list[AudioDevice]`

事前条件: なし。

事後条件:

- 戻り値は `AudioDevice` のリスト。default 先頭、その後 name 昇順 (F1.2)。
- 出力デバイスがゼロ件なら `[]`。

例外:

- `ImportError`: `soundcard` 未インストール。
- `OSError`: `soundcard` の dlopen 失敗 (libpulse / WASAPI 不在)。
- `AudioRoutingError`: 上記以外で予期せず列挙に失敗した場合 (現状想定なし、念のため)。

#### default_device

シグネチャ: `def default_device() -> AudioDevice`

事前条件: なし。

事後条件: OS 既定出力スピーカーを `AudioDevice` として返す。`is_default == True` であること。

例外:

- `DeviceNotFoundError`: 出力デバイスが 1 つも存在しない。
- `ImportError` / `OSError`: `list_devices` と同じ。

#### find_device

シグネチャ: `def find_device(query: str) -> AudioDevice`

事前条件: `query` は `str`。空文字でも形式上受け付けるが §F1.9 の挙動。

事後条件: §F1.6 の 3 段階解決で確定した一意の `AudioDevice` を返す。

例外:

- `DeviceNotFoundError`: 3 段全てで 0 件 (§9 メッセージ書式)。
- `AudioRoutingError`: いずれかの段で複数ヒット (§9 メッセージ書式)。
- `ImportError` / `OSError`: 上記同様。

#### Router クラス

コンストラクタ: `def __init__(self, pid: int, device: str | AudioDevice | None = None, *, chunk_seconds: float = 0.02, blocksize: int | None = None) -> None`

属性 (private、`_` prefix):

- `_pid: int`
- `_device: AudioDevice` (解決済み)
- `_chunk_seconds: float`
- `_blocksize: int | None`
- `_sc_player_ctx: <soundcard player context manager> | None` (start 前は None)
- `_sc_player: <soundcard Player> | None` (start 前は None)
- `_loop: SpeakerLoop | None` (start 前は None)

公開プロパティ:

- `is_running: bool` — `_loop is not None and _loop.is_running`。
- `device: AudioDevice` — `_device` をそのまま返す。

公開メソッド:

- `start(self) -> None`
  - 事前条件: なし (`is_running == True` の場合は no-op で return)。
  - 事後条件: `is_running == True`。
  - 例外: `SpeakerLoop.__init__` / `start` 由来の例外 (`RuntimeError`, `ValueError`, `VRChatMultipleInstancesError`)、soundcard の `player()` / `__enter__` 由来の `OSError` / `RuntimeError`。例外時は内部状態を start 前に戻す。
- `stop(self) -> None`
  - 事前条件: なし (`is_running == False` でも no-op で return)。
  - 事後条件: `is_running == False`、SpeakerLoop と player を解放済み。
  - 例外: SpeakerLoop の worker 例外 (VRChat 死亡など) を再 raise する。player cleanup は finally で必ず実行。
- `close(self) -> None`
  - `stop()` と等価。
- `__enter__(self) -> Self` — `self.start()` を呼んで `self` を返す。
- `__exit__(self, exc_type, exc_val, exc_tb) -> None` — `self.stop()` を呼ぶ。例外は swallow しない。

不変条件:

- `_loop is None ⇔ _sc_player is None ⇔ _sc_player_ctx is None` (3 つ同時に None または同時に非 None)。`start()` / `stop()` の状態遷移後にこの不変条件を保つ。

#### route 関数

シグネチャ: `def route(pid: int, device: str | AudioDevice | None = None, *, chunk_seconds: float = 0.02, blocksize: int | None = None) -> Router`

事後条件: 返却された `Router` は `is_running == True`。呼び出し側がライフサイクル所有。

例外: `Router.__init__` + `Router.start` の合算。`start` 失敗時は Router を返さず例外伝播。

#### 例外型

- `AudioRoutingError(RuntimeError)` — `routing` モジュール由来の全例外の基底。`__init__` は `RuntimeError` のものをそのまま継承。
- `DeviceNotFoundError(AudioRoutingError)` — デバイス解決ゼロヒット専用。

両者の `__all__` 公開を MUST。

### 4.2 CLI `vrcpilot speaker list` 出力 YAML スキーマ

`yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)` で出力。トップキー:

- `devices` (list): 各要素は dict。F1.2 の順序で並ぶ。
  - `id` (str): `AudioDevice.id`。
  - `name` (str): `AudioDevice.name`。
  - `is_default` (bool): `AudioDevice.is_default`。

例 (1 個が既定スピーカー、もう 1 個が VB-Cable Input の Windows ケース):

> devices:
>
> - id: "{0.0.0.00000000}.{aa-bb-...}"
>   name: Speakers (Realtek High Definition Audio)
>   is_default: true
> - id: "{0.0.0.00000000}.{cc-dd-...}"
>   name: CABLE Input (VB-Audio Virtual Cable)
>   is_default: false

ゼロデバイスの場合の出力:

> devices: \[\]

`--json` フラグは導入しない (`ocr` / `detect` / `screenshot` 既存規約と整合)。

### 4.3 CLI `vrcpilot speaker route` の引数と出力

argparse 定義 (擬似):

- `--pid PID` (`type=int`, `required=True`, `metavar="PID"`)
- `--device QUERY` (`type=str`, `default=None`, `metavar="QUERY"`)
- `--chunk-seconds FLOAT` (`type=float`, `default=0.02`, `metavar="SECONDS"`, `dest="chunk_seconds"`)
- `--blocksize N` (`type=int`, `default=None`, `metavar="FRAMES"`)

route 起動時の stderr 1 行サマリ書式:

- `--device` 指定時: `route: pid=<PID> device=<NAME!r>`
- `--device` 省略時: `route: pid=<PID> device=<NAME!r> (system default)`
  - `<NAME!r>` は Python `repr()` 形式 (= 引用符付き、エスケープ有)。例: `route: pid=12345 device='Speakers (Realtek)' (system default)`

停止時の追加出力は MUST 行わない (clean exit を黙って return)。

#### exit code 表

| exit code | 条件                                                                                                                                                                                                             |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0         | `list`: 列挙成功。`route`: Ctrl+C で受信した `KeyboardInterrupt` 経由のクリーン停止。                                                                                                                            |
| 1         | runtime 失敗: `AudioRoutingError` / `DeviceNotFoundError` / `RuntimeError` / `OSError` / `ImportError` / `NotImplementedError` / `VRChatMultipleInstancesError` (`--pid` 必須化で実質起きない)。stderr に 1 行。 |
| 2         | argparse の引数エラー (`--pid` 欠落、型不一致など)。argparse が自動でハンドル。                                                                                                                                  |

CLI `run(args) -> int` は 0 / 1 を返す。2 は argparse 内部で `SystemExit(2)` として出る。

### 4.4 既存 helper との関係

- `cli/_common.py::add_pid_arg`: 本 CLI では `required=True` の `--pid` を要求するため **使わない**。`speaker.py` 内で直接 `parser.add_argument("--pid", required=True, ...)` を書く。
- `cli/_common.py::handle_multi_instance_error`: 本 CLI では `--pid` 必須なので **発生経路がない**。使わない (defensive にも置かない)。
- `mic/devices.py::lookup_speaker`: `find_device` の実装で再利用してよい。ただし `lookup_speaker` は `Mic` のために substring + fuzzy id 解決 (= 部分一致 1 段) であり、本仕様の 3 段階解決とは挙動が違う。**「実装上の下敷きにする」程度に留め、`find_device` は独自実装が望ましい**。`lookup_speaker` を直接呼ぶと「曖昧時に最初の 1 件」になり F1.7 に反する。

## 5. データモデル (Data Model)

| データ             | 型                                     | 永続化      | バリデーション                                                                                                                                                                                        |
| ------------------ | -------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AudioDevice`      | dataclass (frozen=True)                | なし        | `id`, `name` は非空 str (実装側は soundcard が返す値を信用、空白チェックは MUST しない)。`is_default` は bool。                                                                                       |
| Router 内部        | Python オブジェクト参照のみ            | なし        | 不変条件 §4.1。                                                                                                                                                                                       |
| キャプチャフレーム | `NDArray[np.float32]` (shape `(N, 2)`) | なし        | `Speaker.read()` の契約により shape `(N, CHANNELS)` で float32。N == 0 の空フレームを silence tick として許容 (転送はスキップ)。Router は dtype / shape の追加検証は MUST しない (Speaker 契約信頼)。 |
| CLI 設定           | argparse Namespace                     | なし        | argparse が型変換 (`int`, `float`)、`required=True` を強制。                                                                                                                                          |
| YAML 出力          | str (stdout)                           | stdout のみ | §4.2 スキーマ。                                                                                                                                                                                       |

## 6. テスト戦略 (Test Strategy)

### 6.1 設計上の seam — 決定: 「自前 ABC を作らず、Router 内部の soundcard 接触点はそのまま使う。Router 単体テストは全部 integration_real に倒す」

#### 候補比較

| 案                                                                           | 公開 API 影響                                                                       | テストコスト                                                                                                        | プロジェクト哲学整合性                                                                                                                     |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| A. 自前 `OutputSink` ABC を作って Router に DI で注入                        | `OutputSink` が公開シンボル増加 (or private にしても seam の存在を仕様で明文化必要) | unit test で fake を書ける (`tests/fakes/audio.py` 拡張)                                                            | NG: skill 方針「fake できるのは vrcpilot 自前 ABC のみ」を満たすために ABC を増やすのは本末転倒 — 「テストのために抽象を増やす」反パターン |
| B. soundcard 接触点はそのまま、Router の単体テストは integration_real に倒す | 公開 API は最小                                                                     | soundcard 実機が無いとテスト不可。ただし CI Linux runner で PipeWire null-sink、Windows runner で実 WASAPI が使える | OK: skill 方針「実 resource 最優先」と整合。3rd-party 表面 fake を作らない方針もそのまま守れる                                             |
| C. soundcard を module-level 関数経由でアクセスし、テストで monkeypatch      | 公開 API 変化なし                                                                   | 3rd-party 表面 (`soundcard.get_speaker` 等) を mock することになる                                                  | NG: skill 方針で明確に禁止 (`FakeSoundCard*` 新規追加禁止カテゴリ)                                                                         |

**選択: B**。

理由:

- skill 方針 §「3rd-party 表面のモック → 禁止」 + 「`FakeSoundCard*` 新規追加禁止」を最も素直に守れる。
- 公開 API が最小 (`AudioDevice` / `list_devices` / `default_device` / `find_device` / `Router` / `route` + 例外 2 つ) に保てる。`OutputSink` ABC を増やすと、Router の seam を仕様化する責任が永続的に発生する。
- `Speaker` / `SpeakerLoop` が既に自前 ABC として存在し、SpeakerLoop の入出力 (`callback` 経由のフレーム配信、`stop` での例外伝播) は `FakeSpeakerLoop` を介してテストできる。**Router の上流半分 (capture → callback) は ABC 越しに fake 可能、下流半分 (callback → soundcard player) は実機 integration_real**、というハイブリッドが skill 方針と整合する。
- integration_real 用に必要な infra は CI Linux runner の PipeWire null-sink (既に他のテストで構築済み) + Windows runner の実 WASAPI。新規 infra コスト ゼロ。

### 6.2 既存 fake の使い方

- [`tests/fakes/audio.py`](../../tests/fakes/audio.py) の `FakeSpeakerLoop` / `FakeSpeaker` を流用する MUST。新規 fake (`FakeSoundCardSpeaker`, `FakeSoundCardPlayer`, `FakeOutputSink` 等) は **追加しない**。
- プランの「変更対象ファイル」に `tests/fakes/audio.py` を「`FakeSoundcardSpeaker` / `FakeSoundcardPlayer` 追加」と書いてあるが、本仕様では **これを否定する** (skill 方針優先)。Phase 2 の spec-test-author は当該編集を行わない。

### 6.3 テストファイル一覧と区分

ミラーレイアウト (skill §「テストレイアウト」) に従って配置:

| テストファイル                                   | 区分                                           | 対象                                                                                                                                                                                               |
| ------------------------------------------------ | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/vrcpilot/speaker/routing/__init__.py`     | -                                              | 空 (Python パッケージ化のみ)                                                                                                                                                                       |
| `tests/vrcpilot/speaker/routing/test_base.py`    | unit                                           | `AudioDevice` の frozen 性、フィールド、等価判定                                                                                                                                                   |
| `tests/vrcpilot/speaker/routing/test_errors.py`  | unit (公開 API 契約ピンに該当)                 | 例外階層 (`DeviceNotFoundError` is `AudioRoutingError` is `RuntimeError`)。**§契約ピン例外として `tests/vrcpilot/test_api_contract.py` に集約してもよい** (spec-test-author の判断)                |
| `tests/vrcpilot/speaker/routing/test_devices.py` | integration_real                               | `list_devices` / `default_device` / `find_device` の挙動。soundcard 実機が必要 (Linux: PipeWire null-sink を fixture で立てる、Windows: 既定の WASAPI で実機実行)                                  |
| `tests/vrcpilot/speaker/routing/test_router.py`  | integration_real                               | `Router` ライフサイクル全般。実 soundcard player + 実 SpeakerLoop が必要。VRChat 実起動はせず、`FakeSpeakerLoop` で callback だけ駆動するパターンも併用可 (この場合は integration-with-fakes 区分) |
| `tests/vrcpilot/cli/test_speaker.py`             | integration-with-fakes + integration_real 併用 | `list` の YAML 出力、`route` の argparse / stderr サマリ / exit code は fake で。実機 routing の sanity は `integration_real` マーカー付きで別関数                                                 |

### 6.4 テストケース一覧 (FR / NFR 対応)

#### test_base.py (unit)

- T-B1. `AudioDevice(id="x", name="Y", is_default=True)` が作れる
- T-B2. `frozen=True` の検証: `device.id = "new"` が `FrozenInstanceError` を上げる
- T-B3. `slots=True` の検証: 新規属性 `device.foo = 1` が `AttributeError` を上げる
- T-B4. 等価性: 同じフィールドを持つ 2 つのインスタンスは `==` で True

#### test_errors.py (unit / 契約ピン)

- T-E1. `issubclass(DeviceNotFoundError, AudioRoutingError)` is True
- T-E2. `issubclass(AudioRoutingError, RuntimeError)` is True
- T-E3. 例外メッセージのコンストラクタ通過: `str(AudioRoutingError("msg"))` が `"msg"` を含む
- 注: skill 方針では「継承の追試」は基本書かないが、§例外として公開 API 契約ピンは OK。spec-test-author の判断で `tests/vrcpilot/test_api_contract.py` への集約も可

#### test_devices.py (integration_real)

ファイル先頭で:

- Linux: PipeWire null-sink fixture (既存 `tests/conftest.py` 等にある想定、無ければ `tests/fakes/` ではなく `tests/helpers.py` に追加)
- Windows: `sys.platform == "win32"` であれば実 WASAPI で動作

テストケース:

- T-D1. `list_devices()` が空でない (少なくとも 1 個の output device があれば)
- T-D2. `list_devices()` の戻り順序: 先頭が `is_default == True`、後続が name 昇順
- T-D3. `default_device()` が `list_devices()[0]` と一致
- T-D4. `find_device(default_device().id)` が id 完全一致で同じデバイスを返す
- T-D5. `find_device(default_device().name)` が name 完全一致で同じデバイスを返す
- T-D6. `find_device(default_device().name[:3].lower())` が部分一致経路を通る (1 件しかヒットしない名前を選ぶ前提)
- T-D7. `find_device("nonexistent-device-xyzzy")` が `DeviceNotFoundError`
- T-D8. `find_device(<2 件にマッチする substring>)` が `AudioRoutingError` (Linux null-sink を 2 つ立てておく / Windows は WASAPI のデフォルト出力と VB-Cable で重複する文字列を選ぶ)

#### test_router.py

integration_real (実 SpeakerLoop + 実 VRChat 起動不要、ただし soundcard player は実機):

- T-R1. (skip) `Router` ライフサイクル: VRChat 実起動が必要なケースは Phase 6 の e2e で代替し、本テストでは skip マーク

integration-with-fakes (FakeSpeakerLoop を使う、ただし soundcard player は実機を開く):

実装方針: `Router` 自体は `soundcard` を直接呼ぶので、`FakeSpeakerLoop` を Router に差し込むには (a) `vrcpilot.speaker.routing.router` モジュール内で `SpeakerLoop` を import している箇所を monkeypatch する、(b) Router を「SpeakerLoop ファクトリ引数」を取るように拡張する、のいずれか。**(a) を採用** (公開 API を膨らませない)。

- T-R2. `Router(pid=1, device=<AudioDevice instance>).is_running == False` (start 前)
- T-R3. `Router.start()` 後に `is_running == True`、`SpeakerLoop` ファクトリが 1 回呼ばれた
- T-R4. 二重 `start()`: 2 回目は no-op (FakeSpeakerLoop インスタンス数が増えない)
- T-R5. `Router.stop()` 後に `is_running == False`
- T-R6. 二重 `stop()`: 2 回目は no-op (例外を上げない)
- T-R7. コンテキストマネージャ `with route(pid=...) as r:` で `is_running == True`、抜けると False
- T-R8. 空フレーム skip: FakeSpeakerLoop が空 ndarray を callback に渡すと player の play は呼ばれない (player モックではなく、play 呼び出し回数を観測可能な薄い計装が必要 — spec-test-author は実 player の代わりに **player 取得経路を monkeypatch** することは禁止、代わりに **`Router._on_frames` の挙動を直接単体テスト** する形に置き換える)
- T-R9. 非空フレーム転送: FakeSpeakerLoop が非空 ndarray を callback に渡すと player の play が同じデータで呼ばれる (T-R8 と同様、`_on_frames` を直接テスト)
- T-R10. SpeakerLoop 例外伝播: FakeSpeakerLoop の `init_side_effect` で `RuntimeError("vrchat dead")` を仕掛けて `Router.start()` で同例外が raise されること。player は開かれていないので cleanup 不要
- T-R11. SpeakerLoop の worker 例外を stop で受け取る: FakeSpeakerLoop の `stop()` が例外を re-raise する状況を作り (FakeSpeakerLoop に該当機能が無ければ拡張)、Router の stop が同例外を伝播し、player は finally で閉じられること
- T-R12. start 失敗時のロールバック: player は開けたが SpeakerLoop の start で例外が出た場合、player の `__exit__` が呼ばれる。実装で確実に書く必要がある。テストは monkeypatch ではなく、FakeSpeakerLoop の `start_side_effect` を介して再現する (FakeSpeakerLoop に拡張ポイントを追加してもよいが、spec-test-author の判断)
- T-R13. `device` プロパティ: `Router.__init__` で渡した AudioDevice / 解決結果と一致
- T-R14. `stop()` 後の `start()` 再呼び出し: 新しい SpeakerLoop が作られて再起動できる (F2.13)

integration_real (`@pytest.mark.integration_real`):

- T-R15. 実 soundcard player と FakeSpeakerLoop の組み合わせ: `default_device()` の player を開き、FakeSpeakerLoop で zero ndarray を 5 chunks 流し、underrun なく完走することを確認 (耳での確認は e2e、Phase 6)

注意: VRChat 実起動 + 実 Speaker + 実 soundcard までの本物 end-to-end は Phase 6 の手動 e2e で実施する (本仕様の自動テストには含めない)。

#### test_speaker.py (CLI)

integration-with-fakes (Router を `vrcpilot.cli.speaker` モジュール内で参照しているところを monkeypatch — これは「自前モジュールの内部 import 経路の差し替え」であり、skill 方針 §「自分のコードの内部関数モック禁止」とギリギリ抵触するが、**「Router クラス全体を fake クラスで差し替える」は公開 API を ABC 化した場合と本質的に等価で、許容範囲**。spec-test-author の判断で `tests/fakes/audio.py` に `FakeRouter` を追加してよい):

- T-C1. `vrcpilot speaker list` の exit code 0
- T-C2. `vrcpilot speaker list` の YAML スキーマ: `devices` キーが存在、リスト要素が `{id, name, is_default}` の dict
- T-C3. `vrcpilot speaker list` の順序: F1.2 (default 先頭、後続 name 昇順)
- T-C4. `vrcpilot speaker list` が空デバイス時に `devices: []` を出力 (FakeRouter ではなく `list_devices` の monkeypatch、もしくは soundcard の出力がゼロになるよう環境を作る — 後者は困難なので前者で OK。**`list_devices` を空リストに差し替えるのも「自前モジュールの差し替え」**)
- T-C5. `vrcpilot speaker route --pid 12345 --device 'Q'`: argparse 解釈、`FakeRouter` が `pid=12345, device='Q', chunk_seconds=0.02, blocksize=None` で構築される
- T-C6. `--device` 省略時: FakeRouter の `device` 引数が `None`
- T-C7. `--chunk-seconds 0.05`, `--blocksize 256` が FakeRouter に正しく渡る
- T-C8. `--pid` 欠落で SystemExit(2) (argparse の `required=True` 由来)
- T-C9. stderr の 1 行サマリ書式: `--device` 指定時は `(system default)` 接尾辞なし、省略時はあり
- T-C10. Ctrl+C / `KeyboardInterrupt` でクリーン停止 exit 0: `time.sleep` を patch して `KeyboardInterrupt` を投入できる経路を作る (これは stdlib モックなので skill 方針上は注意 — **本テストに限り `time.sleep` の monkeypatch を許容**する。あるいは FakeRouter 側で start 直後に `KeyboardInterrupt` を上げる経路を持たせる方が綺麗。spec-test-author の判断)
- T-C11. SpeakerLoop / Router で `RuntimeError` が出た場合に exit code 1 + stderr 1 行
- T-C12. `DeviceNotFoundError` で exit code 1 + stderr 1 行
- T-C13. `AudioRoutingError` で exit code 1 + stderr 1 行

integration_real (任意、`@pytest.mark.integration_real`):

- T-C14. 実環境で `vrcpilot speaker list` を subprocess.run で実行し、YAML が parse できる (実 soundcard 必須)

### 6.5 マーカー登録

新規マーカーは追加しない。既存の `integration_real` (skill §pytest 設定の含意で言及) を使う。`pyproject.toml` の `[tool.pytest.ini_options] markers` に未登録なら **本仕様の Phase 2 で登録を追加する** (`spec-test-author` の責務に含める)。

### 6.6 doctest

公開 API の docstring に `>>>` 例を **書かない**。`--doctest-modules` 有効下で書く場合は確実に通る例にする必要があるが、`AudioDevice` / `Router` の例は実機依存が強いため doctest 化が困難。docstring は記述のみで `>>>` を含めないこと。

## 7. アーキテクチャ概要 (Architecture)

### モジュール構造

`src/vrcpilot/speaker/routing/` 配下:

- `__init__.py` — 公開 API の再 export。`__all__` で `AudioDevice`, `list_devices`, `default_device`, `find_device`, `Router`, `route`, `AudioRoutingError`, `DeviceNotFoundError` を公開。
- `base.py` — `AudioDevice` dataclass の定義。
- `errors.py` — `AudioRoutingError`, `DeviceNotFoundError` の定義。
- `devices.py` — `list_devices` / `default_device` / `find_device` の実装。soundcard 接触はここに局所化。
- `router.py` — `Router` クラスと `route` 関数。`SpeakerLoop` と soundcard player を結合。

platform 別ファイル (`windows.py` / `linux.py`) は **作らない**。cross-platform で `soundcard` 一本。

### データフロー

> VRChat (PID-scoped audio) → Speaker (vrcpilot, platform 別) → SpeakerLoop (worker thread, callback) → Router.\_on_frames → soundcard.Player.play → 指定スピーカーデバイス

### 外部依存

- `soundcard` (既存 dep): 出力デバイス列挙 + player。
- `numpy` (既存 dep): フレーム ndarray。
- `vrcpilot.speaker` (社内): `Speaker` / `SpeakerLoop` / `SAMPLE_RATE` / `CHANNELS`。
- `vrcpilot.mic.devices` (社内): 任意。再利用するなら `lookup_speaker` のみ参考。

### 責務分割

| ファイル      | 責務                                                                                    | テスト                                                       |
| ------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `base.py`     | `AudioDevice` の不変記述。soundcard 非依存。                                            | unit (`test_base.py`)                                        |
| `errors.py`   | 例外階層。pure Python。                                                                 | unit / 契約ピン (`test_errors.py`)                           |
| `devices.py`  | soundcard.all_speakers / default_speaker / get_speaker のラップ。AudioDevice への変換。 | integration_real (`test_devices.py`)                         |
| `router.py`   | SpeakerLoop と soundcard player の結合。ライフサイクル管理。フレーム転送。              | integration-with-fakes + integration_real (`test_router.py`) |
| `__init__.py` | 公開 API の集約 export。`__all__`。                                                     | api_contract (任意、契約ピン集約に含めても可)                |

## 8. 振る舞い詳細 (Behavior)

### 8.1 主要シナリオ

**S1: `vrcpilot speaker list` で デバイスを列挙**

- Given: 出力デバイスが 2 個存在 (Speakers と CABLE Input)。
- When: ユーザーが `vrcpilot speaker list` を実行。
- Then: stdout に F1.2 順序の YAML が出力され、exit code 0。

**S2: 既定スピーカーへ単一 VRChat の音声をリレー**

- Given: VRChat (PID 12345) が起動済み、`--device` 省略。
- When: `vrcpilot speaker route --pid 12345` を実行。
- Then:
  1. `Router(pid=12345, device=None)` が `default_device()` を解決。
  2. stderr に `route: pid=12345 device='<name>' (system default)`。
  3. `Router.start()` で SpeakerLoop と player を開く。
  4. VRChat の音声が既定スピーカーから再生される。
  5. ユーザーが Ctrl+C → `KeyboardInterrupt` → `__exit__` で stop → exit 0。

**S3: 多重 VRChat の per-PID 分離**

- Given: VRChat が PID 12345 / 67890 で起動済み、CABLE Input が利用可能。
- When: ターミナル A で `route --pid 12345 --device 'CABLE In 16'`、ターミナル B で `route --pid 67890`。
- Then: PID 12345 の音声は CABLE Input へ、PID 67890 の音声は既定スピーカーへ独立して流れる。

**S4: ambiguous device name**

- Given: `Speakers` という文字列が複数デバイス名の部分一致になる環境。
- When: `route --pid 12345 --device Speakers` を実行。
- Then: `find_device` が `AudioRoutingError`、stderr に `vrcpilot: <message>` 1 行、exit code 1。Router は開かれず。

**S5: VRChat プロセス死亡中の relay**

- Given: relay 実行中に VRChat が `vrcpilot terminate` で落ちる。
- When: `Speaker` 内部で I/O が失敗 → SpeakerLoop の worker thread が例外捕捉。
- Then: 次回 `Router.stop()` で SpeakerLoop の `stop()` が例外を再 raise。Router の `__exit__` (Ctrl+C 経由) または `with` ブロック離脱時に player の cleanup を finally で実行した後、SpeakerLoop 例外が伝播。CLI で捕捉して exit code 1。

**S6: route 中に start を二重に呼ぶ (内部 API のみ)**

- Given: `r = Router(...)`、`r.start()` 済み。
- When: `r.start()` を再度呼ぶ。
- Then: no-op で return、状態変化なし。

### 8.2 stop / cleanup の順序

`Router.stop()` の内部順序 (F2.4):

1. ローカル変数に `_loop`, `_sc_player_ctx`, `_sc_player` を退避。
2. インスタンス属性 `_loop`, `_sc_player_ctx`, `_sc_player` を `None` に。
3. `try` ブロック: `loop.stop()` (SpeakerLoop の例外をここで受け取る可能性あり)。
4. `finally` ブロック: `ctx.__exit__(None, None, None)` (player cleanup)。
5. `try` ブロックで捕えた例外があれば re-raise。

これにより:

- player cleanup は必ず実行される。
- SpeakerLoop 例外は player cleanup 後に伝播。
- 二度目の `stop()` は退避時点で 3 つとも None なので何もせず return。

## 9. エッジケースとエラー処理 (Edge Cases & Error Handling)

### 9.1 エッジケース一覧

| ID   | ケース                                                                               | 対応                                                                                                                                                                                                                                                                                          |
| ---- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| EC1  | 出力デバイスが 1 つも存在しない                                                      | `list_devices()` → `[]`、`default_device()` → `DeviceNotFoundError`                                                                                                                                                                                                                           |
| EC2  | `default_device()` で OS 既定が取れない (環境破損)                                   | `DeviceNotFoundError` を投げる                                                                                                                                                                                                                                                                |
| EC3  | `find_device` で id / name / 部分一致のいずれかで複数ヒット                          | `AudioRoutingError` (§9.2 メッセージ)                                                                                                                                                                                                                                                         |
| EC4  | `find_device` で全 3 段ゼロヒット                                                    | `DeviceNotFoundError` (§9.2 メッセージ)                                                                                                                                                                                                                                                       |
| EC5  | VRChat 未起動状態で `route --pid <非存在>` を実行                                    | `Speaker.__init__` 由来の `RuntimeError` (`VRChatNotRunningError` 等)。CLI で exit code 1                                                                                                                                                                                                     |
| EC6  | `--chunk-seconds 0` / 負値                                                           | `SpeakerLoop.__init__` 由来の `ValueError`。CLI で exit code 1                                                                                                                                                                                                                                |
| EC7  | `--blocksize 0`                                                                      | soundcard が `RuntimeError` / `ValueError` を上げる可能性。挙動は soundcard に委ねる (本仕様で追加検証しない)。CLI で exit code 1                                                                                                                                                             |
| EC8  | relay 中に VRChat が死亡                                                             | §S5、SpeakerLoop 例外を stop で受け取り exit code 1                                                                                                                                                                                                                                           |
| EC9  | relay 中に出力デバイスが OS から消失 (USB スピーカー抜去)                            | soundcard player の play が `OSError` / `RuntimeError` を上げる可能性。Router 内部では worker thread からの例外として SpeakerLoop に乗らず、`_on_frames` 内で発生する。**`_on_frames` 内では catch せず raise させる** → 結果として SpeakerLoop の worker thread に伝播 → `stop()` で再 raise |
| EC10 | `Router` の `start()` 中に soundcard player が `__enter__` で失敗 (デバイスロック等) | `Router.start()` から `OSError` / `RuntimeError` が伝播。CLI で exit code 1                                                                                                                                                                                                                   |
| EC11 | start 失敗時のロールバック中に `__exit__(None, None, None)` がさらに例外を上げる     | 元の例外を優先 (Python 仕様)。実装側で chaining せず `raise` で OK                                                                                                                                                                                                                            |
| EC12 | `route` 関数の `Router.start()` 失敗                                                 | Router を返さず例外伝播 (F3.2)                                                                                                                                                                                                                                                                |
| EC13 | コンテキストマネージャで `__exit__` 中に二次例外                                     | Python 仕様: 元の例外と二次例外で context が連結される。実装で抑制しない                                                                                                                                                                                                                      |
| EC14 | `_on_frames` のフレーム dtype が float32 でない                                      | `Speaker` 契約により発生しないはず。実装で MUST 検証しない (信頼)。万が一発生したら soundcard 側で例外                                                                                                                                                                                        |
| EC15 | `_on_frames` のフレーム shape が `(N, 2)` でない                                     | 同上                                                                                                                                                                                                                                                                                          |
| EC16 | 並行: `start()` 中に別スレッドから `stop()` 呼び出し                                 | スコープ外 (Router は単一スレッドからの操作を前提、NF9)。仕様で「`start` / `stop` は呼び出し側の main thread からのみ」と明記。                                                                                                                                                               |
| EC17 | `--pid` に `0` や負値                                                                | argparse は `type=int` で受ける。実 PID として下流 (`Speaker`) で `VRChatNotRunningError` などになる。本仕様で追加検証しない                                                                                                                                                                  |
| EC18 | platform が Win / Linux 以外                                                         | `Speaker.__init__` 由来の `NotImplementedError`。CLI で exit code 1                                                                                                                                                                                                                           |
| EC19 | `pyproject.toml` に `markers = ["integration_real"]` 未登録                          | Phase 2 で MUST 追加 (§6.5)                                                                                                                                                                                                                                                                   |
| EC20 | 既存 `comtypes` 依存の削除を忘れる                                                   | Phase 0 commit で MUST 実施 (§F7.3)                                                                                                                                                                                                                                                           |

### 9.2 エラーメッセージ書式集

実装は以下の `str(exc)` を **substring レベル** で再現する MUST (完全一致は強制しない、テストは `in` で検証)。

- `DeviceNotFoundError` (find_device 3 段ゼロヒット):
  `no output device matches '<query>'. Available output devices:\n  '<name1>' (id='<id1>')\n  '<name2>' (id='<id2>')\n  ...`
  ゼロデバイス時: `no output device matches '<query>'. Available output devices:\n  (none)`
- `DeviceNotFoundError` (default_device、ゼロデバイス):
  `no output device available on this system`
- `AudioRoutingError` (find_device 複数ヒット):
  `multiple output devices match '<query>' (segment=<id-exact|name-exact|name-substring>):\n  '<name1>' (id='<id1>')\n  '<name2>' (id='<id2>')\n  ...\nUse a more specific query (full id or exact name).`
- CLI stderr (ジェネリック): `vrcpilot: <str(exc)>` を 1 行で。複数行の例外メッセージはそのまま `print` してよい (stderr の改行を保つ)。
- CLI route サマリ (再掲): `route: pid=<PID> device=<NAME!r>` または `route: pid=<PID> device=<NAME!r> (system default)`。

## 10. 受け入れ基準 (Acceptance Criteria)

完成判定チェックリスト。すべて MUST 満たす:

### 機能面

- [ ] `from vrcpilot.speaker.routing import AudioDevice, list_devices, default_device, find_device, Router, route, AudioRoutingError, DeviceNotFoundError` がエラーなし
- [ ] `vrcpilot.speaker.routing.__all__` が上記 8 つ全てを含む
- [ ] `AudioDevice` は `frozen=True, slots=True` の dataclass
- [ ] `DeviceNotFoundError` is `AudioRoutingError` is `RuntimeError`
- [ ] `list_devices()` の戻り順序が F1.2 通り
- [ ] `find_device` の 3 段階解決が F1.6 / F1.7 / F1.8 通り
- [ ] `Router` の二重 `start` / `stop` が no-op
- [ ] `Router.__exit__` が player → SpeakerLoop の順で cleanup
- [ ] `route` ヘルパが `Router` を構築 + `start` して返す

### CLI 面

- [ ] `vrcpilot speaker list` が §4.2 スキーマの YAML を stdout に出力、exit 0
- [ ] `vrcpilot speaker route --pid <N>` で `--device` 省略時に既定スピーカーへ relay 開始、stderr に `(system default)` 付きサマリ
- [ ] `vrcpilot speaker route --pid <N> --device <Q>` で `--device` 指定時に解決後デバイスへ relay
- [ ] `--pid` 欠落で exit code 2 (argparse)
- [ ] Ctrl+C で exit code 0
- [ ] 例外時に stderr に `vrcpilot: <msg>` 1 行 + exit code 1
- [ ] `--chunk-seconds 0.02`、`--blocksize None` が既定値

### 品質面

- [ ] `just run` (format + test + type) すべて green
- [ ] `pyright --strict` で型エラー 0
- [ ] `ruff check` / `ruff format` で警告 0
- [ ] `tests/vrcpilot/speaker/routing/` の単体テストが green
- [ ] `pytest -m integration_real tests/vrcpilot/speaker/routing/` が CI Linux runner + Windows runner で green

### 依存面

- [ ] `pyproject.toml` から `comtypes` が削除されている
- [ ] `uv.lock` が再生成されている

### ドキュメント面

- 本仕様の対象範囲外 (docstring / docs 更新は Phase 5 の docstring-author 担当)

## 11. 実装計画 (Implementation Plan)

承認済みプランの Phase 構造に従う。本仕様は Phase 1 の成果物。

### Phase 2 並列実装: 担当領域 disjoint 確認

| エージェント                                  | 触るファイル                                                                                                                                                                                                                                                                       | 触ってはいけないファイル                                                          |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **A. spec-driven-implementer (routing コア)** | `src/vrcpilot/speaker/routing/__init__.py`、`base.py`、`errors.py`、`devices.py`、`router.py`                                                                                                                                                                                      | `tests/` 全般、`src/vrcpilot/cli/`、`pyproject.toml`、`tests/fakes/`              |
| **B. spec-driven-implementer (CLI)**          | `src/vrcpilot/cli/speaker.py` (新規)、`src/vrcpilot/cli/__init__.py` の `_COMMANDS` に 1 行追加                                                                                                                                                                                    | `src/vrcpilot/speaker/routing/`、`tests/` 全般、`tests/fakes/`、`pyproject.toml`  |
| **C. spec-test-author (routing テスト)**      | `tests/vrcpilot/speaker/routing/__init__.py`、`test_base.py`、`test_errors.py`、`test_devices.py`、`test_router.py`、必要なら `pyproject.toml` の markers に `integration_real` 追加、必要なら `tests/fakes/audio.py` に `FakeRouter` のみ追加 (FakeSoundcard\* は **追加しない**) | `src/vrcpilot/` 全般、`src/vrcpilot/cli/` 全般                                    |
| **D. spec-test-author (CLI テスト)**          | `tests/vrcpilot/cli/test_speaker.py`                                                                                                                                                                                                                                               | `src/vrcpilot/` 全般、`src/vrcpilot/cli/` 全般、`tests/vrcpilot/speaker/routing/` |

C と D が共有編集する可能性のあるファイル:

- `tests/fakes/audio.py`: C が `FakeRouter` を追加するなら D も触る可能性。**起動前に C / D で「`FakeRouter` の追加は C 担当」と取り決める**。D は import するのみ。
- `pyproject.toml` の `markers = ["integration_real"]` 登録: C 担当。D は触らない。

並列起動順:

1. Phase 0 (準備): `comtypes` 削除、`uv lock`、ブランチ作成 (シーケンシャル)。
2. Phase 1 (本仕様): 完了。
3. Phase 2: A / B / C / D を 1 メッセージ内で並列起動。
4. Phase 2 後: orchestrator が `just run` を実行。
5. テスト失敗が出たら、disjoint なモジュール毎に A / B を並列再起動。テストは触らない (C / D の領域)。テストが間違っているという疑義があれば C / D に再起動して回答を取る。

### Phase 3 (Phase 2 と並列可): docs/virtual-audio.md と CLAUDE.md の更新

担当 disjoint: ドキュメント担当 (E) が `docs/` と `CLAUDE.md` を編集。`src/` / `tests/` には触らない。本仕様策定の責務外。

### Phase 4 (リファクタ): code-quality-reviewer

- A. routing コア (`src/vrcpilot/speaker/routing/`) のリファクタ
- B. CLI (`src/vrcpilot/cli/speaker.py`) のリファクタ

public API 不変、tests 触らない。

### Phase 5 (docstring): docstring-author

- 公開 API 全てに docstring を追加。`>>>` は書かない (NF6 / §6.6)。

### Phase 6 (手動 e2e): プラン §6 通り

## 12. 未解決事項 (Open Questions)

仕様確定段階で残った保留事項 — Phase 2 着手前にユーザー判断が必要なものを列挙。

| Q   | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | 判断者                                | 期限             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------- | ---------------- |
| Q1  | T-R8 / T-R9 (空フレーム skip / 非空フレーム転送) は `Router._on_frames` を直接呼ぶ単体テストに倒すと記述したが、`_on_frames` は private メソッドであり、テストから直接呼ぶことの是非。**仕様判断**: private メソッドのテストは `feedback_private_module_convention.md` で「テストするなら prefix を外す」とあるが、これはモジュール単位の話。メソッド単位では skill 哲学 §「内部実装の詳細はテストしない」と衝突する。Phase 2 で spec-test-author が **integration_real (実 player 越し)** で T-R8 / T-R9 を観察可能な形に置き換える方が clean。 | spec-test-author (Phase 2)            | Phase 2 内で確定 |
| Q2  | `FakeRouter` を `tests/fakes/audio.py` に追加するか、`tests/vrcpilot/cli/test_speaker.py` 内で local class とするか。skill 方針 §「共有 fake は `tests/fakes/` に集約」と整合させるなら前者だが、Router は公開 API クラスなので「`tests/fakes/audio.py` は自前 ABC の fake のみ」原則とは微妙にズレる (Router は ABC ではなく concrete class)。                                                                                                                                                                                                  | spec-test-author (Phase 2)            | Phase 2 内で確定 |
| Q3  | T-C10 の `KeyboardInterrupt` テストで `time.sleep` を patch するか、`FakeRouter.start()` から直接 raise させるか。前者は skill 方針 §「`time.sleep` のモック禁止」に抵触気味、後者の方が清潔。**推奨: 後者** (`FakeRouter` に `raise_on_start_complete=KeyboardInterrupt` のような knob)。Q2 と同時に確定する。                                                                                                                                                                                                                                  | spec-test-author (Phase 2)            | Phase 2 内で確定 |
| Q4  | `find_device` の F1.6 段階遷移を「同じ段で複数ヒット → 即エラー」と規定したが、「id exact で 1 件あればそれを返す」のは intentional。プランの記述「3段階解決」と整合するが、ユーザー側で「name 完全一致が優先されるべき」という別解釈があれば仕様変更要。**現状の仕様は plan §3 と整合**。                                                                                                                                                                                                                                                       | ユーザー (再確認)                     | Phase 2 着手前   |
| Q5  | T-R12 (start 失敗時の player ロールバック) を spec-test-author が integration-with-fakes で書くには `FakeSpeakerLoop` の `start_side_effect` knob が必要。現状 `FakeSpeakerLoop` には `init_side_effect` のみ。`tests/fakes/audio.py` を編集して knob 追加するのは C の責務 — D には影響しない。                                                                                                                                                                                                                                                 | spec-test-author (Phase 2 内、C 担当) | Phase 2 内で確定 |
| Q6  | Phase 0 の `comtypes` 依存削除を Phase 1 終了時点で orchestrator が実施するか、Phase 2 で実装エージェント A に含めるか。プランでは「Phase 0 シーケンシャル」と明記されている → orchestrator 実施。                                                                                                                                                                                                                                                                                                                                               | orchestrator                          | Phase 2 着手前   |

## 13. 将来の拡張余地 (Future Work)

スコープ外だが意識しておくべき発展方向:

- **`route-many` サブコマンド**: 単一コマンドで複数 (PID, device) ペアを扱う。v2 で `vrcpilot speaker route-many --pair PID=DEVICE --pair PID=DEVICE` の形で導入余地。
- **音量制御**: `Router.set_volume(0.0..1.0)` で出力ゲインを変える。`numpy` の素のスカラ乗算で実装可能。
- **デーモンモード**: `vrcpilot speaker daemon` で background 常駐、unix socket / named pipe で制御。
- **メトリクス出力**: `--metrics` フラグで relay レイテンシ / underrun カウントを stderr に定期出力。
- **AudioDevice の追加メタデータ**: `channels` / `default_samplerate` / `is_virtual` 等。soundcard が提供できる範囲で。
- **EarTrumpet / pavucontrol との hybrid 構成のドキュメント化**: docs/virtual-audio.md に既存 GUI ツールとの組み合わせパターンを記載 (Phase 3 担当)。

## 14. 該当なし

以下の項目は本仕様では該当なし:

- 永続化: 状態は全て in-memory。設定ファイル / レジストリ書き込みなし。
- 認証: ローカル CLI、認証なし。
- ネットワーク: ループバック含めて使用しない。OSC とは独立。
- データマイグレーション: 旧 IAudioPolicyConfig 経路の永続化レジストリエントリは別途 cleanup する必要があるが、本仕様のスコープ外 (旧仕様の `vrcpilot speaker reset` を最後に実行してから移行することをユーザーへ案内する程度。docs に追記 Phase 3)。

______________________________________________________________________

## 付録: Phase 2 並列実装ハンドオフサマリ (200 字以内)

> 仕様パス: `memory/specs/pid_speaker_routing_relay.md`。Phase 2 4 並列起動キー: §4 (API) / §6.3-6.4 (テスト一覧) / §11 (担当 disjoint 表)。テスト seam 決定は §6.1 (案 B: 自前 ABC 増やさず integration_real 中心)。Open Question Q1-Q5 は spec-test-author が Phase 2 内で確定可、Q6 は orchestrator が Phase 0 で実施。
