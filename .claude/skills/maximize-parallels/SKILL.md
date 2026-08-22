---
name: maximize-parallels
description: 独立な tool 呼び出しは 1 メッセージにまとめて並列発火する。並列化可能の判定基準 (出力 → 入力の依存なし / 共有 mutable state を同時に書かない / tool 固有の排他なし)、典型的に並列化すべきパターン、逐次必須の落とし穴 (Read→Edit 連鎖、同 file への複数 Edit、cd を伴う Bash)、vrcpilot 固有の並列化ポイント (just test と just type は並列可、just e2e-test は不可)、着手前の依存グラフ判定手順。複数タスクに着手する / 複数 file を読む / 長めの bash 列を組む前に読む。
---

# 並列化を最大化する

複数の tool 呼び出しを行うとき、論理的に独立なものは **1 メッセージに複数の tool_use ブロックを並べて発射** する。速度・コスト・体感応答性の単純改善であり、迷ったら並列を選ぶ。

## 並列化可能の判定基準

以下 3 つを全て満たすときに並列化できる。1 つでも引っ掛かるなら逐次。

1. **出力 → 入力の依存がない**: 一方の stdout / 戻り値 / 副作用が他方の入力に使われない
2. **共有 mutable state を同時に書き換えない**: 同じ file への並列 Edit、同じ branch への並列 checkout は不可
3. **tool 固有の排他がない**: `Bash` の cwd 切り替えのように session 内で副作用を残すものは並列禁止。`Read` / `Grep` / `Glob` は読み取り専用で常に安全

## 並列化すべき典型パターン

- **複数 file の `Read`**: 何を読むかが事前に決まっているなら一気に並列で読む。1 件読んで「次は何を読むべきか」を考えるのは遅い
- **独立な `Bash`**: `git status` / `git diff` / `git log` のように互いを汚さない情報取得
- **検索の発散**: 複数の角度から同時に探す (`grep "pulsectl"` / `grep "soundcard"` / `find -name 'linux.py'`)
- **複数エージェントの起動**: 担当領域が disjoint なら常に並列 → [agent-team](../agent-team/SKILL.md)

## vrcpilot 固有の並列化ポイント

- **`just test` と `just type` は並列に回せる**。pytest は `.venv`、pyright も読み取りのみで、互いに書くものが無い
- **`just format` は単独で回す**。pre-commit が file を書き換えるので、読み取り系と並列にすると読んだ内容が古くなる
- **`just e2e-test` は他の何とも並列にしない**。VRChat プロセス・X display のフォーカス・`/dev/uinput`・PipeWire sink・OSC UDP port (9000/9001)・クリップボードは **すべて OS 全体で 1 つ** の共有資源。並列に走らせると入力が混ざり結果が不定になる → [do-on-worktree](../do-on-worktree/SKILL.md) の共有 state 表
- **`src/` の実装と `tests/` のテストは常に並列**。担当エージェントが分かれており file が disjoint

## 並列化してはいけない (逐次必須) パターン

- **`Read` → `Edit` / `Write` 連鎖**: `Edit` / `Write` は事前 `Read` を要求する。同じ file の `Read` と `Edit` を並列に出すと後者が失敗する
- **同じ file への複数 `Edit`**: 後続の `Edit` は前の適用後のテキストを `old_string` として参照するため、並列にすると 2 つ目以降が見つからない
- **`cd` を伴う `Bash`**: cwd は session 内で持続するので、並列に走らせると後続コマンドがどの cwd で動くか不定。各 Bash で絶対パスを使うか `cd dir && cmd` のように 1 Bash 内に閉じ込める
- **依存する出力**: `git rev-parse HEAD` の結果を次の `git show <sha>` に渡すような場合
- **同じ branch / worktree への破壊的操作**: `git checkout` / `git switch` / `git stash` を並列に走らせない

## 着手前の判定手順

複数タスクに取り掛かる直前に (必要なら書き出して) これをやる:

1. 各タスクの **入力** と **出力** を 1 行で書き出す
2. あるタスクの出力が別のタスクの入力に現れるか確認する → 現れたらその 2 つは逐次
3. 同じ file / branch / OS 資源を書くタスクがないか確認する → あれば逐次
4. 残ったものを 1 メッセージにまとめて発射する

依存があるタスクは「依存グループ」内では逐次、**グループ間は並列にできる**。5 タスクのうち 2 つに依存関係があるなら、3 並列 + 2 逐次であって全部逐次ではない。

「全部逐次に並べてから後で並列化を検討する」は遅い。**最初から並列を前提に組む。**
