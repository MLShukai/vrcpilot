---
name: write-docs
description: vrcpilot のユーザー向けドキュメント規約。docs/ と repo root の役割分担、bilingual 対訳ペア (X.md / X.ja.md) と言語スイッチャ行の形式、mdformat が全 markdown に掛かる前提、docs/python-api.md が手書きゆえに起きる drift、CHANGELOG 規約、変更種別ごとに更新すべき file、仕上げ前の 5 点 drift audit。README / docs/ / CHANGELOG を書く前に読む。
---

# ドキュメント規約

vrcpilot のユーザー向け文書は **手書き markdown**。docstring から自動生成する仕組み (mkdocstrings 等) は無い。つまり **公開 API を変えたら `docs/` は手で追従させる必要がある**。

## 1. どこに何があるか

| 置き場所                                                | 対象                                                                |
| ------------------------------------------------------- | ------------------------------------------------------------------- |
| repo root `README.md`                                   | 入口。Features / インストール / サブコマンド表 / 各 docs へのリンク |
| [docs/cli.md](../../../docs/cli.md)                     | フラグ単位の CLI リファレンス                                       |
| [docs/python-api.md](../../../docs/python-api.md)       | `vrcpilot.<name>` の公開シンボル手書きリファレンス                  |
| [docs/usage.md](../../../docs/usage.md)                 | タスク指向のウォークスルー (起動 → 観測 → 行動 → 検証)              |
| [docs/virtual-audio.md](../../../docs/virtual-audio.md) | 仮想オーディオ (speaker / mic) の実践ガイド                         |
| repo root `CONTRIBUTING.md`                             | 開発者向け (ブランチ / リリース / 検証)。**bilingual 化しない**     |
| [docs/RELEASE.md](../../../docs/RELEASE.md)             | maintainer 向けリリース手順。**bilingual 化しない**                 |
| `CHANGELOG.md`                                          | Keep a Changelog 形式。`## [Unreleased]` に追記していく             |

`docs/` は原則 **公開サイト相当 (ユーザー向け)**。`RELEASE.md` だけは maintainer 向けだが歴史的経緯で `docs/` にある — 新しい maintainer 向け文書を足すなら repo root を選ぶ。

## 2. bilingual 対訳ペア

以下は **英語版が正、`*.ja.md` が対訳** のペア。**片方だけ更新して終わらない。**

- `README.md` ↔ `README.ja.md`
- `CODE_OF_ETHICS.md` ↔ `CODE_OF_ETHICS.ja.md`
- `docs/{cli,python-api,usage,virtual-audio}.md` ↔ 同名 `.ja.md`

各ファイルの H1 直後に言語スイッチャ行を置く。**自分の言語を太字、相手をリンク**にする:

```markdown
# CLI Reference

**English** | [日本語](cli.ja.md)
```

```markdown
# CLI リファレンス

[English](cli.md) | **日本語**
```

`.ja.md` 内の相互リンクは `.ja.md` 同士で閉じる (日本語版の `cli.ja.md` からは `usage.ja.md` を指す)。言語スイッチャ行以外で英語版へのリンクを混ぜない。

日本語版の書き方: コード・識別子・ファイルパス・コマンド・確立した技術用語 (PipeWire, uinput, OSC, scancode) は **原形のまま**。訳すとかえって読みにくくなる。

## 3. mdformat が全 markdown に掛かる

pre-commit の `mdformat` (+ gfm / tables / frontmatter、`--number`) は `docs/` も `.claude/` も除外なしで通る。したがって:

- **テーブルを手で桁揃えしない**。mdformat が正規化する
- 番号付きリストは `--number` で連番に振り直される
- MkDocs Material 記法 (`!!!` admonition 等) は使わない。plain GFM 前提
- 迷ったら書いてから `just format` に整形させる

codespell も全 markdown に掛かる。固有名詞で誤検知したら綴りを直すか、`.pre-commit-config.yaml` の skip を増やすのではなく表現を変える。

## 4. `docs/python-api.md` の drift

`docs/python-api.md` は公開シンボルを **手書きで列挙している**。自動生成ではないので:

- `src/vrcpilot/__init__.py` の `__all__` に足したシンボルは、ここにも手で足す
- 関数シグネチャを変えたら該当節を手で直す
- 冒頭に「シグネチャは `<version>` 時点のソースに対応」と書かれている。実質的に更新したらこのバージョン表記も見直す

API の意味論の真実は docstring 側にある。`docs/python-api.md` に説明を書き足すより **docstring を直してから転記する** 方が筋が良い。

## 5. 変更種別ごとに更新するもの

| 変更                           | 更新先                                                                                        |
| ------------------------------ | --------------------------------------------------------------------------------------------- |
| CLI サブコマンド / 引数        | `docs/cli.md` + `.ja.md`、`README` のサブコマンド表 → [cli-design](../cli-design/SKILL.md) §9 |
| 公開 Python API                | `docs/python-api.md` + `.ja.md`、`README` の Features                                         |
| 新しいサブシステム             | `README` の Features、`docs/usage.md` に使い方、必要なら専用ガイド                            |
| 音声系の挙動                   | `docs/virtual-audio.md` + `.ja.md`                                                            |
| ブランチ / リリース / 検証手順 | `CONTRIBUTING.md`、`docs/RELEASE.md` (単一言語)                                               |
| ユーザーに見える変更すべて     | `CHANGELOG.md` の `## [Unreleased]`                                                           |

## 6. 仕上げ前の drift audit

`README.md` / `README.ja.md` / `CONTRIBUTING.md` / `tests/e2e/README.md` を触ったら、終わる前にこの 5 点を現在の `src/` に突き合わせる。ユーザーの依頼が API drift に触れていなくても実行する:

1. **Features リスト vs `src/vrcpilot/__init__.py` の `__all__`** — 新しい公開サブシステムが出ても箇条書きが遅れる
2. **CLI サブコマンド表 vs `cli/__init__.py` の `_COMMANDS`** — 追加が漏れる。直下の argcomplete リストはテストで pin されているので安価な oracle になる
3. **`launch` の説明** — direct-spawn が既定 (Linux は常に、Windows は opt-in)。「through Steam」のまま残っていることがある
4. **backend ファイル名** — 規約は `windows.py` / `linux.py`。旧名 (`win32.py` / `x11.py` / `proctap.py` / `pipewire.py`) が散文に残っていることがある
5. **`tests/e2e/README.md` のシナリオ表** — `all.py` が兄弟 `*.py` を自動発見するので、README を触らずシナリオを足すと静かに stale になる。`ls tests/e2e/*.py` が真実

スコープ外の drift は勝手に直さず **報告する**。詳細: [memory/agents/docstring-author/project_user_docs_drift_audit.md](../../../memory/agents/docstring-author/project_user_docs_drift_audit.md)

## 7. 計画・設計ドキュメント

`memory/specs/` の仕様書やユーザーに提示する設計案は **日本語で書く**。コード・識別子・コマンドは英語のまま → [memory/feedback_planning_doc_language.md](../../../memory/feedback_planning_doc_language.md)

これはユーザー向け `docs/` の規約 (英語が正) とは別軸。混同しない。
