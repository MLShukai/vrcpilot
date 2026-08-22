---
name: agent-team
description: マルチエージェントによる 設計 → 実装/テスト並列 → 修正ループ → リファクタ → docs のフロー。5 エージェント (spec-planner / spec-driven-implementer / spec-test-author / code-quality-reviewer / docstring-author) の責務分離、フェーズごとの並列起動数、orchestrator 中継規約、起動して良い規模の下限。「エージェントチームで」と指示されたとき、または複数モジュールにまたがる仕様を実装するときに読む。
---

# エージェントチーム戦略

「エージェントチームで行う」と指示され、具体的な手順が示されていない場合にこのサイクルに従う。エージェント定義は [.claude/agents/](../../agents/)。

## 起動して良い規模

サブエージェント委譲は **本当に独立していて規模のあるトラック** に対してのみ引き合う。以下は起動しない:

- 自分で数回の tool 呼び出しで終わる作業
- 自分の作業を検証・ダブルチェックさせる目的 (自己検証は自分でやる)
- 1 エージェントで終わる仕事に複数エージェントを当てる

**ユーザーが明示的にチーム運用を求めていない限り起動しない。** 単一モジュールの小さな変更は自分で実装 → `just run` で足りる。

## 責務分離

各エージェントの担当領域は **厳密に分離** されており、互いの領域に踏み込まない。

| エージェント              | 書く対象                                     | 触ってはいけない対象                      |
| ------------------------- | -------------------------------------------- | ----------------------------------------- |
| `spec-planner`            | 仕様書 `memory/specs/*.md` (コードなし)      | コード全般                                |
| `spec-driven-implementer` | `src/vrcpilot/`                              | `tests/` (テストは絶対に編集しない)       |
| `spec-test-author`        | `tests/` (`fixtures/` 含む)                  | `src/vrcpilot/`                           |
| `code-quality-reviewer`   | `src/vrcpilot/` 内部 (public API は不変)     | `tests/`、public API、CLI 引数、`__all__` |
| `docstring-author`        | docstring・コメント・`docs/`・`CHANGELOG.md` | ロジック                                  |

## 実装サイクル

### フェーズ 1: 設計

`spec-planner` が要件を分析し、インターフェース設計と実装計画を `memory/specs/` に策定する。コードは書かない。

仕様が固まったら orchestrator が内容を確認し、独立したモジュール / 機能に分割可能かを判断する。分割できるならフェーズ 2 の並列度がそのまま決まる。

### フェーズ 2: 実装 + テスト (並列)

`spec-driven-implementer` と `spec-test-author` を **同じメッセージで並列起動**。仕様を共通の入力とし、実装者は `src/` を、テスト著者は `tests/` を書く。**テストは実装を見ずに仕様から書く** (実装に引きずられないことでテストが仕様書として機能する)。

- 1 つの仕様に対して常に 2 エージェント並列
- 仕様が独立した N モジュールに分割可能なら 2N エージェント並列

vrcpilot での自然な分割単位: platform backend (`windows.py` / `linux.py`)、サブパッケージ (`speaker/` / `mic/` / `controls/`)、`cli/` サブコマンド。これらは互いに独立に実装・テストできることが多い。

### フェーズ 3: 実装修正ループ

`spec-driven-implementer` がテストを通すように `src/` **だけ** を修正する。**テストコードは絶対に触らない**。

テストが間違っていると思われる場合は orchestrator に質問を返す。orchestrator が `spec-test-author` にリレーし、テストの修正可否を判定するのは `spec-test-author` の責務。独立モジュールごとに実装者を並列起動できる。

### フェーズ 4: 検証クリア

`just run` (format → test → type) がパスし、実機の振る舞いに関わる変更なら `just e2e-test <NAME>` もパスしてスクリーンショットまで確認したら次へ。

### フェーズ 5: リファクタリング

`code-quality-reviewer` が public API を一切変えずに内部を整える (重複排除・簡素化・命名・型精緻化)。`tests/` は触らない。各ステップで `just test` を回して green を保つ。独立モジュールごとに並列起動できる。

### フェーズ 6: ドキュメンテーション

`docstring-author` が docstring・コメント・`docs/`・`CHANGELOG.md` を整える。ロジックには触らない。`docs/` は bilingual なので対訳ペアを揃える → [write-docs](../write-docs/SKILL.md)。

## 並列化

担当領域が disjoint であることが並列化の前提 (同じ file を 2 エージェントが同時に編集しない)。結果は orchestrator が統合し、コンフリクトが起きたら逐次に切り替える。同じ file を触りうるエージェントを並列にしたいなら `isolation: "worktree"` → [do-on-worktree](../do-on-worktree/SKILL.md)。tool 呼び出しレベルの並列化は [maximize-parallels](../maximize-parallels/SKILL.md)。

## エージェント間通信

エージェント同士は直接通信できない。すべて orchestrator (親) が中継する:

- 実装者 → テスト著者の質問 → orchestrator が `spec-test-author` を起動して回答を取り、実装者に渡す
- 仕様の解釈が分かれる → orchestrator がユーザーに確認するか、`spec-planner` を再起動して仕様を更新する
- リファクタで public API を変えたくなった → `code-quality-reviewer` は実施せず改善案として報告。判断は orchestrator / ユーザー
- `docstring-author` がバグや設計上の問題を見つけた → 直さず報告。orchestrator が実装者に回すか、仕様レベルなら `spec-planner` に戻す

## サイクル完了後

1. `just run` (と必要なら `just e2e-test`) が green であることを orchestrator 自身が確認する
2. [git-ops](../git-ops/SKILL.md) の規約でコミットする
3. PR を出すなら [merge-main](../merge-main/SKILL.md) → [github-pr](../github-pr/SKILL.md)
4. 各エージェントの知見が `memory/agents/<name>/`、プロジェクト全体の知見が `memory/` に記録されているか確認する
