---
name: do-on-worktree
description: メインの作業ツリーを汚さずにサブタスクを隔離実行する。EnterWorktree / Agent の isolation:"worktree" を第一選択とし、手動なら .claude/worktrees/<name>。worktree ごとに uv sync が必要な点と、VRChat プロセス・X display・/dev/uinput・PipeWire sink・OSC port という OS レベル共有 state の扱い、後始末。別ブランチで隔離実行する / 本流を汚さずに試す前に読む。
---

# worktree でサブタスクを隔離する

**いつ使うか**: 本流の作業を中断せずに別の変更を試したいとき、同じ file を触りうる複数エージェントを並行させたいとき、大きめのリファクタを本流に混ぜずに検証したいとき。

**いつ使わないか**: 読み取りだけの調査。同じ file を触らない並列作業 ([maximize-parallels](../maximize-parallels/SKILL.md) の通常の並列で足りる)。worktree は 1 つあたり `uv sync` のコストが乗るので安易に増やさない。

## 第一選択: harness の worktree 機能

- `EnterWorktree` / `ExitWorktree` — 現在のセッションを隔離した worktree に移す
- `Agent` の `isolation: "worktree"` — サブエージェントを専用 worktree で走らせる。**同じ file を書きうるエージェントを並列起動するときはこれを使う**

サブエージェントは既定で親セッションの作業ディレクトリを共有する。担当領域が disjoint なら共有のままでよい ([agent-team](../agent-team/SKILL.md) のフェーズ 2 は `src/` と `tests/` で分かれているので隔離不要)。

## 手動で作る場合

```bash
git fetch origin main
git worktree add .claude/worktrees/<name> -b <種別>/$(date +%Y%m%d)/<slug> origin/main
cd .claude/worktrees/<name> && just setup
```

- `.claude/worktrees/` は gitignore 済み、かつ `.claude/settings.json` の `additionalDirectories` に登録済み
- ブランチ名は [git-ops](../git-ops/SKILL.md) の規約に従う。ベースは `origin/main` (ローカル `main` が古い可能性があるため)
- **`uv sync` は worktree ごとに必要**。`.venv` は共有されない (uv のキャッシュは効くので実ダウンロードは初回のみ)

## worktree をまたぐ共有 state

worktree は file system 上は独立だが、以下は **OS / プロセスレベルで共有される**。複数 worktree で同時に触ると結果が不定になる。vrcpilot は OS 結合が支配的なので、ここが最大の落とし穴。

| 共有される state                   | 影響するもの                                     | 対処                                                                                                 |
| ---------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| **VRChat プロセス / PID**          | `just e2e-test`、`vrcpilot launch` / `terminate` | **同時に走らせない**。1 つの worktree で完了してから次へ。`terminate` は他 worktree の VRChat も殺す |
| **X display / フォーカス**         | `focus` / `unfocus` / `capture` / `screenshot`   | 前面ウィンドウは 1 つ。並列実行するとどちらのキャプチャか区別できない                                |
| **`/dev/uinput` デバイス**         | `controls/keyboard` / `controls/mouse` の e2e    | 入力は OS 全体に届く。同時に叩くとキーが混ざる                                                       |
| **PipeWire sink / 仮想マイク**     | `mic` / `speaker` / `linux-mic register`         | sink 名は global。`VRCPilotMic` の register / unregister を並列にしない                              |
| **OSC UDP port (9000 / 9001)**     | `osc` サブコマンド、`tests/e2e/osc.py`           | port は排他。同時 bind は失敗する                                                                    |
| **クリップボード**                 | `paste` / `clipboard`                            | OS 全体で 1 つ。並列に書くと内容が飛ぶ                                                               |
| **git のオブジェクトストア / ref** | `git switch` 等                                  | 同じブランチを 2 worktree で checkout できない (git が拒否する)                                      |
| **uv のキャッシュ**                | `uv sync`                                        | 並行実行に安全。気にしなくてよい                                                                     |

`just test` (pytest) と `just type` は worktree 内に閉じるので複数 worktree で同時に走らせて問題ない。**`just e2e-test` は絶対に並列にしない。**

## 成果の取り込み

1. **PR にする**: そのまま push して [github-pr](../github-pr/SKILL.md)。レビューを通す価値がある変更ならこちら
2. **メインの作業ブランチに merge する**: メイン側で `git merge <worktree-branch>`。調査結果を取り込むだけの小さい変更ならこちら

どちらの場合も、取り込む前に worktree 内で `just run` が green であることを確認する。

## 後始末

```bash
git worktree remove .claude/worktrees/<name>    # 変更が残っていると拒否される
git worktree list                               # 消えたことを確認
git branch -d <種別>/<日付>/<slug>              # 不要ならブランチも消す
```

変更を捨ててよいと **明示的に判断できる場合のみ** `--force` を使う。判断がつかないなら残してユーザーに確認する。使い終わった worktree を放置しない。

## やってはいけないこと

- worktree 内から `main` に commit する
- 複数 worktree で `just e2e-test` を同時に走らせる (上表のすべてが衝突する)
- 変更が残っている worktree を確認せず `remove --force` する
- `.claude/worktrees/` の外に worktree を作る (gitignore が効かず後始末も追いにくくなる)
