---
name: reference-pw-link-behavior
description: Empirically-measured pw-link/pw-record (PipeWire 1.0.5) behavior for per-PID VRChat audio isolation — only global-port-id linking is deterministic AND collision-free under 2 same-named VRChat nodes; capture also needs explicit port-id link (--target name falls back to default sink); pw-dump object shapes for parser stubs
metadata:
  type: reference
---

Measured on this machine (libpipewire 1.0.5) for the speaker/linux.py pw-link migration.

## Connect syntax

`pw-link OUTPUT INPUT` (output first). `-L/--linger` is default for connect.

## Only explicit port-pair form has deterministic returncode

`pw-link "<node.name>:output_FL" "<tap>:playback_FL"`:

- success → rc=0, no stderr
- already-linked (idempotent) → rc=255, stderr `failed to link ports: File exists`
- non-existent port → rc=255, stderr `failed to link ports: No such file or directory`

## Node-granularity forms are UNRELIABLE for returncode branching

`pw-link <node.name> <tap.name>`, `pw-link <node.id> <tap.name>`, `pw-link <id> <id>`:
all return rc=255 with `Input & output port do not exist` / `No such file or directory`
**even when they successfully create the FL/FR links** (pw-link tries to match every
candidate port incl. monitor/aux and fails on the non-matching ones while still creating
the channel-matched links). Sometimes they create 0 links. Do NOT branch on returncode
for these forms. Numeric-prefixed port form `<node.id>:output_FL` does NOT resolve.

## Port naming

Ports are `<node.name>:<port.name>`, channels `output_FL`/`output_FR` (source),
`playback_FL`/`playback_FR` (null-sink input). `pw-link -o`/`-i` list them; `-I` prefixes
the **port id** (not node id). Node id only appears in `pw-dump` (Port object props `node.id`).

## pulsectl sink_input → PipeWire node identifiers

sink_input proplist exposes: `object.id` (= PipeWire node id), `object.serial`,
`node.name`. The pulsectl `sink_input.index` equals `object.serial`. So from a pulsectl
sink_input you can build the explicit port spec via `node.name`.

## DECISIVE: only GLOBAL PORT ID form is deterministic AND collision-free (2 VRChat)

Verified with two producers both forced to `node.name=VRChat.exe` (the real 2-instance
collision), distinct tones (440/880 Hz), two taps (tap_A/tap_B):

- **port-NAME form** `pw-link "VRChat.exe:output_FL" "tap_A:playback_FL"` rc=0 but
  ALWAYS resolves the SAME one producer — `tap_A` and `tap_B` both got the 440 producer;
  the 880 producer was unreachable by name. **Unusable for multi-instance.**
- **node-id / node-name forms** rc=255 even on success (see above). Unusable.
- **GLOBAL PORT ID form** `pw-link <out_port_global_id> <in_port_global_id>`: rc=0 on
  success, rc=255 + `failed to link ports: File exists` on idempotent re-link. True
  isolation: tap_A captured pure 440 (mag@880=0.0), tap_B pure 880 (mag@440=0.0), each
  RMS=0.2121. **This is the form to use.**

Global port id = the Port object's top-level `id` (== its props `object.id`); NOT the
per-node `port.id` (always 0 for FL). `pw-link -o -I` prints global port ids but with
colliding node.name you CANNOT tell which port belongs to which node from CLI alone —
**must use `pw-dump` Port objects' `node.id` prop to map node→ports.**

## CAPTURE side also needs explicit port-id linking (not --target name)

`pw-record --target=<sink>.monitor` and `--target=<node id>` / `PIPEWIRE_NODE=<id>` all
get REDIRECTED by Wireplumber to the DEFAULT SINK monitor when >1 sink exists (the
node's `target.object` is set correctly but the session manager links it to node 48 =
alsa default sink). Confirmed: capture returned the default mix, not the tap. The
deterministic capture: start `pw-record --target=0` (no autoconnect, input ports stay
free), then `pw-link <tap monitor_FL global port id> <pw-record input_FL global port id>`.
That gave true per-tap isolation. NOTE: this differs from the current production code
which uses `--target=<tap>.monitor` — that only works by luck when a single tap exists.

## pw-record direct from a producer does NOT work

`pw-record --target=<producer node>` cannot capture a `Stream/Output/Audio` producer —
Wireplumber redirects to the default sink monitor (producers have no capturable monitor).
The null-sink tap remains necessary.

## pw-record node identity (capture-side node resolution)

A `pw-record` node does NOT expose `application.process.id` in its pw-dump props (it is
`None`) — you cannot find your own pw-record node by its OS pid. It DOES respect
`-P 'node.name=<unique>'` (e.g. `vrcpilot_rec_<pid>`), and that name appears in pw-dump
Node props `node.name`. Use a unique per-pid record node.name + find-by-name; collision-
free when 2 backends run (plain `node.name=='pw-record'` collides). The record node's
input ports are `input_FL`/`input_FR` (direction `in`, audio.channel FL/FR); it also has
`monitor_FL/FR` (direction `out`) so always filter ports by direction.

## pulsectl sink_input → PipeWire identifiers (the code bridge)

sink_input proplist: `object.id` = PipeWire **node** id (string, e.g. '112'),
`object.serial` (== pulsectl `sink_input.index`), `node.name`. pulsectl does NOT expose
port ids — code must `pw-dump` and match Port objects by `node.id` == that node id,
`port.direction=='out'`, `audio.channel in {FL,FR}`, take each Port's top-level `id`.

## pw-dump object shapes (for parser stubs)

Node: `{id, type:"PipeWire:Interface:Node", info.props:{object.id, object.serial, node.name, media.class:"Stream/Output/Audio", application.process.id, media.name}}`.
Port: `{id (GLOBAL port id), type:"PipeWire:Interface:Port", info.props:{node.id, object.id (==id), port.name:"output_FL", port.alias:"VRChat.exe:output_FL", port.direction:"out", audio.channel:"FL"}}`.
Link: `{id, type:"PipeWire:Interface:Link", info:{output-node-id, output-port-id, input-node-id, input-port-id, state:"active"}}` — output-node-id is the producer node.
pw-dump piped directly is RACY (intermittently empty/invalid JSON); write to a file then
parse.

## Audio path verified (single-tap, legacy)

Explicit-port link from a producer (kept on the default sink too) to a null-sink tap,
then `pw-record --target=<tap>.monitor` → non-silent (RMS 0.2115, peak 0.3000). Producer
stays audible on default sink (UX: user still hears VRChat). Wireplumber does NOT revert
user-created explicit links (unlike sink_input_move / target.object metadata). But the
`--target=.monitor` capture only works reliably with ONE tap (see capture-side note).
