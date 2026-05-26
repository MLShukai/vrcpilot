---
name: platform-specific-helpers-placement
description: Platform-specific helper functions must be defined inside the corresponding platform module (linux.py / windows.py), not in cross-platform base.py — even when "convenient" to share with CLI.
metadata:
  type: feedback
---

`src/vrcpilot/<modality>/base.py` のような cross-platform 共有モジュールには、**そのプラットフォーム固有の概念 (PipeWire sink 名・PulseAudio description・config ファイル名など)** を扱うヘルパを置いてはいけない。たとえ複数モジュール (例: `mic/linux.py` と `cli/linux_mic.py`) から参照されていても、置き場所は当該 platform モジュール (`mic/linux.py`) の内部であるべき。

**Why:** ユーザーは「`sink_name_for` / `description_for` のような Linux 依存のものは完全に Linux でのみ定義される」状態を望んでいる。base.py に置くと非 Linux 環境からも import 可能になり「完全に Linux only」を破る (実際は呼んでも動かない/意味がない関数が見えてしまう)。`mic/linux.py` 内に置けば `if sys.platform != "linux": raise ImportError(...)` のガードで自然に到達不能になる。

**How to apply:**

- 新規ヘルパを追加するとき、まず「これは platform-specific な概念を扱うか?」を自問
  - Yes → `<modality>/<platform>.py` の中で定義 (公開 / private のどちらでも platform ガード後の領域に置く)
  - No (本当に cross-platform で、Windows/Linux/macOS どこでも意味を持つ) → `<modality>/base.py`
- 公開パスは `vrcpilot.mic.linux.sink_name_for` のような形になる。`vrcpilot.mic` トップから re-export しない (re-export すると非 Linux 環境でも見える)
- 複数 platform-specific モジュール (例: `mic/linux.py` と `cli/linux_mic.py`) から共用したい場合も、定義は `mic/linux.py` 側に置き、`cli/linux_mic.py` から `from vrcpilot.mic.linux import ...` で取る (両方とも Linux ガード後なので問題なし)
- 既存の cross-platform 定数 (例: `VIRTUAL_MIC_SINK_NAME`) は base.py に残しておいてよい。Linux デフォルトデバイス名として `mic/devices.py` 側 (cross-platform) も参照しているため

判定 sanity check: 関数名や戻り値に platform 固有の語彙 (PipeWire / Pulse / pactl / WASAPI / VB-Cable など) が直接出てくるなら、それは platform 側に置く。
