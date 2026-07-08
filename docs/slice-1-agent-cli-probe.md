# Slice 1 Spec: Agent CLI Probe

## Goal

Slice 1 verifies that a real Agent CLI actually invokes commands through Mica's PATH shims before Mica claims governance over that agent.

The first target is OpenCode. This slice is observational: it records shim hits and builds a hit-rate matrix. It does not block, approve, reject, or claim full policy enforcement for agent runs.

## Probe Mode

`mica-proxy` supports probe mode through environment variables:

```powershell
$env:MICA_PROXY_MODE = "probe"
$env:MICA_PROBE_LOG = "<repo>\.mica\opencode-probe.jsonl"
```

In probe mode:

- every shim hit appends one JSONL event
- the risk policy is evaluated and recorded
- no approval is created
- no command is blocked
- the real command still executes
- stdout, stderr, and exit code still pass through

Probe events include `timestamp`, `tool`, `argv`, `command_line`, `cwd`, `real_executable`, `requires_approval`, `risk_level`, and `reason`.

## Probe Summary

Summarize any probe log:

```powershell
$env:PYTHONPATH = "<repo>\proxy"
python -m mica_probe --log .mica\opencode-probe.jsonl --expect git,npm,terraform
```

The output is JSON with total hits, expected tools, per-tool hit state, commands, and hit rate.

`total_hits` counts every shimmed external command observed during the run. Agent CLIs may invoke additional commands internally; OpenCode commonly runs extra `git` commands for repository detection and snapshots. The Slice 1 acceptance signal is the per-tool hit matrix, not a literal total of three commands.

## OpenCode Probe

Use:

```powershell
.\scripts\probe-opencode.ps1
```

The script:

- checks that `opencode` exists
- puts `shims/` first in PATH
- preserves the original PATH in `MICA_ORIGINAL_PATH`
- enables `MICA_PROXY_MODE=probe`
- writes `.mica/opencode-probe.jsonl`
- runs `opencode run --auto` with fixed commands:
  - `git status`
  - `npm -v`
  - `terraform --version`
- prints the `mica_probe` hit matrix

If OpenCode is not installed, it exits `2`; that is an environment gap, not a governance result.

## Acceptance Criteria

- A command run through shims records probe JSONL events.
- Probe mode never creates approvals.
- Probe mode never blocks execution.
- `mica_probe` reports hit/miss for `git`, `npm`, and `terraform`.
- `probe-opencode.ps1` can run against an installed OpenCode CLI and produce `.mica/opencode-probe.jsonl`.

Verified on 2026-07-06 with local OpenCode: `git`, `npm`, and `terraform` all hit the shims, with `hit_rate=1.0`. The run produced many `git` hits because OpenCode performed internal repository and snapshot operations in addition to the requested `git status`.

## Interpretation

- High hit rate: proceed to command approval integration for that agent.
- Partial hit rate: inspect which commands bypassed PATH and why.
- Zero hit rate: do not claim governance; inspect the agent's execution mechanism.

Probe results are evidence. Without probe results, Mica should not claim it can govern a specific Agent CLI.
