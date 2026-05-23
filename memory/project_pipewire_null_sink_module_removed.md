---
name: pipewire-null-sink-module-removed
description: vrcpilot mic enable が書き出す libpipewire-module-null-sink は pipewire 1.0+ で廃止されており、ユーザーが一度有効化すると PipeWire daemon ごと起動不能になる
metadata:
  type: project
---

`mic/linux.py` が `$XDG_CONFIG_HOME/pipewire/pipewire.conf.d/vrcpilot-mic.conf` に書き出す `context.modules = [{ name = libpipewire-module-null-sink, ... }]` は、pipewire 0.3 後期〜1.0 でモジュールが廃止されており Ubuntu 24.04 (pipewire 1.0.5) のモジュールディレクトリ `/usr/lib/x86_64-linux-gnu/pipewire-0.3/` に `libpipewire-module-null-sink.so` が存在しない。

結果、`pipewire.service` が `pw.conf: could not load mandatory module "libpipewire-module-null-sink"` → `failed to create context` → exit 254 で起動するたびに即死し、systemd の rate-limit (`Start request repeated too quickly, restart counter is at 5`) に当たって自動再起動も停止する。`pipewire-pulse.service` は別 unit なので生き続け、空ソケットに繋ぎに来た client へ `Host is down` を返す。OS 再起動しても drop-in conf は消えないので毎回同じ場所で死に、ユーザー視点では「PulseAudio がいきなり死んで何をしても治らない」現象になる。

**Why:** pipewire 1.0 で null-sink は独立 module をやめて `module-adapter` + `factory.name = support.null-audio-sink` (context.objects 経由) に統合された。vrcpilot の conf テンプレートは旧書式のまま残っており、しかも `flags = [ ifexists nofail ]` 等の安全弁もないため mandatory load 失敗が daemon 全体を巻き込む。

**How to apply:** `mic/linux.py` を触るとき、または「Linux で PipeWire/PulseAudio が死んだ」という報告を受けたときは:

1. まず `~/.config/pipewire/pipewire.conf.d/vrcpilot-mic.conf` の有無を確認し、退避すれば復旧することを伝える
2. systemd rate-limit を `systemctl --user reset-failed pipewire.service pipewire-pulse.service wireplumber.service` で必ず解除する (再起動だけでは解除されないことがある)
3. テンプレートを直す場合は `context.objects = [{ factory = adapter, args = { factory.name = support.null-audio-sink, ... }}]` 形式へ移行する。`media.class` は Sink 運用なら `Audio/Sink`、純粋に Virtual Source として見せるなら `Audio/Source/Virtual`
4. 同種事故を再発させない安全弁として、書き出した conf を試験ロードして失敗したら enable を fail させる、もしくは module 読み込みに `flags` を付ける運用を検討する

関連: \[\[vrchat-cli-playbook\]\] (mic は VRChat 検証フローでも使う)
