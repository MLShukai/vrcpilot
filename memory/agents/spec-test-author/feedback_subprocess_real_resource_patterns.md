---
name: subprocess を real-resource として使うパターン (terminate / wait_for_pid 系)
description: subprocess.Popen / psutil.Process / psutil.pid_exists が絡む検証は、3rd-party seam を mock せず実 child を spawn して PID 操作で代替する
metadata:
  type: feedback
---

`vrcpilot.process` の `terminate(pid)` / `wait_for_pid(pid=)` / `wait_for_no_pid(pid=)` のような「実 PID を相手取る API」のテストで、`subprocess.Popen` / `psutil.process_iter` / `psutil.Process` / `psutil.pid_exists` をモックせずに real-resource で組む定型パターン:

**生きている PID が必要なら**:

```python
@pytest.fixture
def short_lived_subprocess() -> Iterator[subprocess.Popen[bytes]]:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5.0)
```

**死んでいる PID が必要なら** (再利用衝突を避けるため「とても大きい数」は使わない):

```python
def _doomed_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"], ...)
    pid = child.pid
    child.wait(timeout=5.0)
    # zombie 状態で psutil.pid_exists がまだ True を返すことがあるので poll
    deadline = time.monotonic() + 5.0
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return pid
```

**Why:**

- `subprocess.Popen` も `psutil.*` も 3rd-party 表面なので新方針でモック禁止。実 child を spawn する以外に取れる手は無い
- Python interpreter の child は名前が `python` / `python3` 等で確実に `VRChat.exe` ではないので、`terminate(pid)` の「名前が違うので ValueError」分岐をその PID で再現できる (impostor として活用可能で、最初から impostor 扱いなので絶対にキルされない)
- 「PID `99999`」のような大きい数字を使うと、長時間稼働ホストで実プロセスと衝突する flaky の原因になる。spawn→wait→reap で得た PID は確実に historical なので NoSuchProcess を必ず再現できる
- ホスト OS は exit 直後に zombie を一瞬残すので、`psutil.pid_exists` が False に落ちるまで短いポーリングが必要 (5s timeout で十分)

**How to apply:**

- `wait_for_pid(pid=X, timeout=2.0)` で X が alive → real child の PID を使う
- `wait_for_no_pid(pid=X, timeout=0.1)` で X が alive (timeout False を確認したい) → real child を使い、tiny timeout でリターンを早める
- `wait_for_no_pid(pid=Y, timeout=2.0)` で Y が dead (True を期待) → `_doomed_pid()` を使う
- `terminate(non_vrchat_pid)` で ValueError を期待 → real child の PID を使う (絶対にキルされないので fixture teardown が安全)
- `terminate(reaped_pid)` で `[]` を期待 (silently skip 分岐) → `_doomed_pid()` を使う
- positive path (`terminate` が実際に kill する / `find_pids` が VRChat を見つける) は e2e 担保。conftest の autouse `_no_real_vrchat` を個別テストで上書きするのは禁止

関連: shared な [テスト戦略 4 区分](../../feedback_test_strategy.md), [feedback_fakes_mirror_production.md](feedback_fakes_mirror_production.md)
