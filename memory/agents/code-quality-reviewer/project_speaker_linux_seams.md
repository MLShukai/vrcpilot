---
name: speaker-linux-seams
description: vrcpilot.speaker.linux per-PID PipeWire backend — pinned test seams, log-prefix contract, and pure-helper surface a refactor must not break
metadata:
  type: project
---

`src/vrcpilot/speaker/linux.py` (`PipeWireSpeakerBackend`) has a wide
test+e2e contract that constrains refactoring. Before touching it, know:

**Pinned test seams (signatures frozen — tests `mocker.patch.object` them):**
`_pw_link_run_raw(args: list[str])`, `_pw_dump_raw() -> bytes`,
`_open_pulse`, `_spawn_pw_record`, `_module_load_raw`.

**Pure helpers tested directly (signature + return-meaning frozen, body free):**
`_parse_pw_dump`, `_find_node_id_by_name`, `_find_node_id_by_process_id`,
`_find_ports`, `_extract_tap_pid`. `_find_node_id_by_process_id` is
production-dead (pw-record nodes don't publish `application.process.id`)
but has `TestFindNodeIdByProcessId` — do NOT delete from src; report only.

**Log-prefix contract (tests + e2e grep these pipe-delimited prefixes):**
`port link ok` / `port link already present` / `port link failed | ...returncode=...` / `port link summary | src_node=...dst_node=...channels=...`
/ `pw-link stderr | ...` / `on_pulse_event | facility=...type=...self_pid=...`
/ `sink_input candidate` / `sink_input scan summary`. Preserve prefix AND
field names.

**Internal (free to refactor — NOT in tests):** `_wait_for_tap_ready`,
`_wait_for_record_node`, `_resolve_vrchat_node_ids`, the `_safe_*` teardown
helpers, `_link_existing_vrchat_nodes_to_tap`, `_link_tap_monitor_to_record`.

**Why:** test_linux.py treats project-owned ABCs/seams as the only legit
fake points (3rd-party surfaces pulsectl/subprocess.Popen are off-limits per
testing policy), and Phase A e2e reconstructs failures purely from the log
stream.

**How to apply:** confine refactors to helper bodies + internal methods +
private dispatch. Reuse `_coerce_optional_int` / `_optional_str` /
`_dump_props` for proplist narrowing, and `_poll_for(probe)` for the shared
`_SINK_LOOKUP_RETRIES`/`_SINK_LOOKUP_INTERVAL_SEC` readiness loop. Verify with
`uv run pytest tests/vrcpilot/speaker/ -q` then `uv run pyright src/vrcpilot/speaker/linux.py`.
