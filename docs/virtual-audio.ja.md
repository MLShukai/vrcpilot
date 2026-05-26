# 仮想オーディオガイド

[English](virtual-audio.md) | **日本語**

VRChat の出力音声を PID 単位で別デバイスへ振り分けるためのガイド。`vrcpilot speaker` の使い方、補助ツールとの組み合わせ、レイテンシ調整の指針をまとめる。CLI のフラグ単位の詳細は [`cli.ja.md`](cli.ja.md) を、Python API は [`python-api.ja.md`](python-api.ja.md) を参照。

______________________________________________________________________

## 概要

VRChat を多重起動 (multi-instance) したとき、各 PID の出力音声を別々の物理 / 仮想スピーカーへ分離したい、というのが本機能の解決対象。OS レベルのアプリ別出力先割り当て (Windows の `IAudioPolicyConfig`、EarTrumpet) は内部で **exe path ベースの AppIdentity** に解決されるため、同一 `VRChat.exe` を多重起動した場合の per-PID 分離を API 仕様レベルで保証できない。さらに VRChat は `start_protected_game.exe` 経由で本体プロセスを生やすため、ポリシー登録系の API は soft fail することがある。

vrcpilot は既に **PID 単位の音声キャプチャ** を持っている (Windows: proc-tap、Linux: PipeWire native、いずれも 48 kHz / stereo / float32)。これを `soundcard` で任意の出力デバイスへユーザー空間でリレーすれば、OS policy に依存せず per-PID 分離が成立する。クライアント改造 (EAC 違反) も不要。

______________________________________________________________________

## 仕組み

```
VRChat (PID=N) ──[proc-tap / PipeWire capture]──> vrcpilot.Speaker
                                                         │
                                                         ▼
                                          soundcard.Player (任意の出力デバイス)
```

キャプチャ → 出力の素直な合成。OS のポリシーには触れない。Windows / Linux で同じコードパスを共有する (platform 別ファイルは持たない)。

トレードオフはレイテンシ追加。総追加レイテンシは `chunk_seconds` (キャプチャ側) と `blocksize` (出力側) で調整する。既定は `chunk_seconds=0.02` (20 ms) で低レイテンシ寄り。

______________________________________________________________________

## 基本的な使い方

### デバイス列挙

```bash
vrcpilot speaker list
```

stdout に YAML で出力スピーカー一覧が出る。`is_default: true` のものが OS 既定。

```yaml
devices:
  - id: "{0.0.0.00000000}.{...}"
    name: Speakers (Realtek High Definition Audio)
    is_default: true
  - id: "{0.0.0.00000000}.{...}"
    name: CABLE Input (VB-Audio Virtual Cable)
    is_default: false
```

### リレー開始

```bash
vrcpilot speaker route --pid 12345 --device "CABLE Input"
```

`--pid` は必須 (多重起動を扱う前提なので自動 resolve はしない)。`--device` には `list` で得た `id` か `name` の完全一致、もしくは部分一致 (大文字小文字無視) を渡す。曖昧マッチで複数ヒットした場合はエラー終了する。

foreground 動作。Ctrl+C で停止し exit code 0 で抜ける。VRChat プロセスが落ちた場合は exit code 1 で停止する。

`--device` を省略すると **OS 既定スピーカー** が選ばれる。route 開始時に解決後のデバイス名が stderr に `route: pid=12345 device='Speakers (Realtek)' (system default)` の形で 1 行表示される。

### レイテンシ調整

```bash
vrcpilot speaker route --pid 12345 --device "CABLE Input" \
    --chunk-seconds 0.05 --blocksize 1024
```

- `--chunk-seconds` (既定 `0.02`): キャプチャ単位の秒数。小さいほど低レイテンシ、大きいほど underrun (音の途切れ) に強い。
- `--blocksize` (既定 `None` = soundcard デフォルト): 出力側バッファのフレーム数。

______________________________________________________________________

## 仮想スピーカーデバイス

**仮想スピーカーは任意**。物理スピーカーへ直接リレーしても動作する。多重インスタンス分離や他ツール (DAW、配信ソフト) との連携が必要な場合だけ仮想デバイスを導入する。

### Windows

代表的な仮想ケーブル系ツール (いずれも導入後に Windows の再起動が必要なものが多い):

- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) — 単一の `CABLE Input → CABLE Output` ペアを提供。多重 cable が必要なら有償の `CABLE A/B/C/D` 版を使う。
- [VB-Audio Voicemeeter Banana](https://vb-audio.com/Voicemeeter/banana.htm) — 3 系統入力 + 仮想 cable 2 系統。ミックスやモニタリングが要るなら有力。
- [Virtual Audio Cable (VAC)](https://vac.muzychenko.net/en/) — 有償。任意数の仮想 cable を立てられる。

インストール後、`vrcpilot speaker list` の出力に新しいデバイスが現れることを確認。

### Linux

PipeWire は仮想 sink を動的に立てられる。**事前に常駐 daemon を導入する必要はない**。

その場で 1 つ作る:

```bash
pactl load-module module-null-sink \
    sink_name=vrchat_pid_1 \
    sink_properties=device.description=VRChat_PID_1
```

`vrcpilot speaker list` の出力に `VRChat_PID_1` が現れる。アンロードは:

```bash
pactl unload-module $(pactl list short modules | grep vrchat_pid_1 | cut -f1)
```

永続化したい場合は `~/.config/pipewire/pipewire.conf.d/` 配下に config を置く。`vrcpilot linux-mic register` 系の機構も同じ仕組みを使っているので、実装例として参考になる ([`mic/linux.py`](../src/vrcpilot/mic/linux.py))。

______________________________________________________________________

## mic 側との衝突に注意

`vrcpilot mic` は **VB-Audio Virtual Cable の `CABLE Input` を既に使用している**。ここに route 先として同じ cable を指定すると、

```
VRChat → speaker route → CABLE Input ─┐
                                              │
            CABLE Output → VRChat マイク入力 ←┘ (VRChat 側で設定済み)
```

というフィードバックループが成立し、自分の音声が自分に戻ってエコー・ハウリングが発生する。

回避策:

- 別の仮想 cable を使う (`CABLE-A Input` / `CABLE-B Input` などの追加版を導入)。
- Voicemeeter / VAC で別系統を構築する。
- そもそも仮想デバイスを使わず、物理スピーカーへ直接 route する。

Linux でも同じ。`VRCPilotMic` (mic 側) と route 先 sink は別の sink にする。

______________________________________________________________________

## Windows 補助ツール: EarTrumpet 連携

[EarTrumpet](https://eartrumpet.app/) は Windows のアプリ毎オーディオを GUI で管理できる無料 OSS ツール (Microsoft Store / GitHub release から入手可)。vrcpilot と組み合わせる典型パターンは 2 つ:

**用途 1: 単一インスタンスで vrcpilot route を使わない**

VRChat を 1 つしか立てないなら、EarTrumpet で `VRChat.exe` の出力先デバイスを直接指定するのが最も手軽。`vrcpilot speaker route` は不要。

**用途 2: 多重 VRChat で hybrid 構成**

EarTrumpet で「VRChat 全体」を仮想 cable (`CABLE Input` 等) に流しておき、各 PID は `vrcpilot speaker route --pid <N> --device <出力先>` で個別に振り分ける。

### 注意

EarTrumpet は内部で `IAudioPolicyConfig` を使っている。これは exe path ベースの AppIdentity 解決を行うので、**同一 `VRChat.exe` の多重起動を per-PID 分離する目的には使えない**。多重インスタンス分離は引き続き vrcpilot relay が担う。

______________________________________________________________________

## Linux 補助ツール: PipeWire 系 GUI

PipeWire 環境では以下の GUI ツールがアプリ単位ルーティングに使える。

- [pavucontrol](https://freedesktop.org/software/pulseaudio/pavucontrol/) — PulseAudio (PipeWire の Pulse 互換層) 向けの GUI。Playback タブからアプリ単位で sink を選べる。UX は EarTrumpet に最も近い。
- [Helvum](https://gitlab.freedesktop.org/pipewire/helvum) — PipeWire ネイティブのグラフエディタ。stream ↔ sink を線で結ぶ。
- [qpwgraph](https://gitlab.freedesktop.org/rncbc/qpwgraph) — Helvum と同系統のグラフエディタ。Qt ベースで Helvum より高機能。

インストール例:

```bash
# Debian / Ubuntu
sudo apt install pavucontrol helvum qpwgraph

# Fedora
sudo dnf install pavucontrol helvum qpwgraph

# Arch
sudo pacman -S pavucontrol helvum qpwgraph
```

### 注意

PipeWire の手動結線は **VRChat 再起動で剥がれる**。インスタンスを立て直すたびに GUI で結線し直すことになるので、永続的な per-PID 分離は vrcpilot relay 推奨。GUI ツールは「単一インスタンス」または「hybrid 構成 (vrcpilot route と併用)」向け。

______________________________________________________________________

## レイテンシ調整ガイド

既定は `chunk_seconds=0.02` (20 ms)、`blocksize=None` (soundcard デフォルト) で低レイテンシ寄りに振っている。

判断フロー:

1. まず既定で route してみる。
2. 音が途切れる (underrun) / プチプチ鳴る場合は `--chunk-seconds 0.05` 程度まで段階的に上げる。
3. それでも不安定なら `--blocksize 2048` 等で出力バッファを大きく取る。
4. 体感レイテンシが大きすぎると感じる場合は逆に `--chunk-seconds 0.01` まで下げる余地もある (CPU 負荷と underrun リスクとのトレードオフ)。

### 実測の目安 (Phase 6 e2e 観察)

- **Windows 11 (Ryzen / Realtek + VB-Cable + DELL モニタ出力)**: 既定 `chunk_seconds=0.02` で underrun なし。VRChat の起動・ミュート切替・UI 効果音などのトランジェントを目安に「会話のレイテンシ感」程度の遅れに留まり、`record` 経由のキャプチャ波形と並べて聴感差は感じにくいレンジ。
- 同条件で 2 多重 VRChat (`--profile 0` / `--profile 1`) を起動し、PID#1 → Realtek 内蔵スピーカー、PID#2 → VB-Cable In 16ch へ独立にリレーした際、両方の経路が proc-tap → soundcard の合成で互いに干渉なく独立に流れることを確認 (OS policy 非依存の per-PID 分離が成立)。
- `integration_real` マーカー付きの単体テスト (`pytest -m integration_real tests/vrcpilot/speaker/routing/`) は 26 件すべて 2-3 秒 で green。Router の start/stop 周回や空フレーム透過は実 soundcard 越しに収束する。
- **既知の制約**: route 実行中に VRChat プロセスが死亡しても、CLI は `time.sleep` ループに留まる (内部 SpeakerLoop の例外は次回 `Router.stop()` で初めて surface する仕様)。ユーザーは Ctrl+C で能動的に停止する必要がある。将来の改善余地 (route ループ内で `Router.is_running` を polling) は本リリース範囲外。
