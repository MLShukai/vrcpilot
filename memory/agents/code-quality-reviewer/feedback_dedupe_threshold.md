---
name: 重複は本当に動く 2 つ目を見てから抽出する
description: feature-based detect engine の重複を 1 引数 + 1 helper だけで済ませた判断 — 抽出のタイミングを早すぎず遅すぎず取る話
metadata:
  type: feedback
---

このプロジェクトでは「先回りで helper を切り出すより、2 つ目の実装が出て同じ形が固まってから抽出する」のが好まれる傾向がある。

**Why:** `vrcpilot.detect` の `sift.py` が初出時、SIFT 専用の helper を `_geometry.py` に切り出さなかった。AKAZE が後続で同じ Homography + RANSAC パイプラインを再利用する段になって初めて `_geometry.py` を作り、scale/rotation 復元 + NMS + polygon projection の 4 つだけを抽出した。SIFT/AKAZE の `detect()` 本体（grayscale 化 → keypoint 抽出 → ratio test → 反復 RANSAC ループ）はまだ重複したまま残してある。これは「extractor の差し替えだけで済むなら一度抽出したいが、`AKAZE_create(threshold=...)` のような extractor 固有 kwarg がもう一段増えると helper の I/F が膨張しがち」という保留判断。実際 Template engine が来てデフォルトを取ったので、feature-based 同士のさらなる抽出はコストに見合わない可能性が高い。

**How to apply:** 2 エンジン目を見たタイミングで helper 切り出しを **検討** はしてよい。ただし helper の引数が「extractor だけ差し替えれば共通化できる」状態になっているか確認する。extractor 固有のパラメータ (descriptor matcher の選択、threshold 等) が加わって I/F が肥大しそうなら、後続のエンジンが本当にそのパイプラインを踏襲するか確認するまで抽出を保留する。3 つ目が来てパターンが固まってから抽出するほうが結局シンプルになることが多い。今回でいえば Template が SIFT/AKAZE と全く違うパイプラインだったので、feature-based 同士の `detect()` 本体抽出は不要だった。
