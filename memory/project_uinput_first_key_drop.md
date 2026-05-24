---
name: Linux uinput デバイスは初回入力が drop される
description: inputtino.Keyboard / Mouse は uinput デバイス作成直後の最初の入力が X11 hot-plug 遅延で silently drop される。LinuxKeyboard/LinuxMouse の __init__ で 0.5s 待つ
metadata:
  type: project
---

`vrcpilot.controls.keyboard.linux.LinuxKeyboard.__init__` / `vrcpilot.controls.mouse.linux.LinuxMouse.__init__` は `inputtino.Keyboard()` / `inputtino.Mouse()` で `/dev/uinput` 仮想デバイスを作成した直後に **`time.sleep(0.5)`** を必ず入れる。これより短いと最初の 1 入力が黙って捨てられる。

**Why:** 2026-05-24 に `tests/e2e/osc.py` と `tests/e2e/detect.py` で「warmup 直後の `keyboard.press(Key.ESCAPE)` で Launch Pad が開かない」という症状が報告された。CLI 経由 (`vrcpilot keyboard press escape`) では同じコードが正常動作する一方、Python 同一プロセス内では再現する。原因は uinput デバイスの kernel 登録は同期だが、udev → X11 (libinput) の subscribe は非同期で 100-200ms 遅延し、その窓に入った入力イベントは「kernel → evdev は届くが X11 リスナがまだ無い」状態で捨てられること。
`tests/e2e/keyboard.py` (4 回 Esc トグル) は最初の 1 回が落ちても 4_open_again / 5_close_again の最終状態が post-cleanup と整合するため「動いている風」に見えていた。osc.py / detect.py は最初の 1 回が「メニューを開く唯一の入口」だったため隠れていた問題が顕在化した。v0.2.x にも同じ潜在バグはあった (constructor は同じ)。

**How to apply:**

- Linux backend の `__init__` で `inputtino.{Keyboard,Mouse}()` を呼ぶ直後に `time.sleep(_UINPUT_BIND_SETTLE)` (= 0.5s) を必ず置く。0.5s は計測上の余裕込みの値で、これより短くすると環境差で再発する
- 「初回 0.5s が遅い」という理由でこの sleep を削らない。代替策は「ダミーキーを 1 回撃って捨てる」だが、副作用が不確定なので採用しない
- Windows backend (`Win32Keyboard` / `Win32Mouse`) には不要 (`SendInput` は直接 OS の入力キューに積むので hot-plug 遅延の概念がない)
- 関連: \[\[project_keyboard_press_duration\]\] (こちらは VRChat / Unity 側の short-keypress drop で別問題)
