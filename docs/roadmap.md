# Roadmap

## Product North Star

Mica is an AI Coding Agent Execution Control Plane focused on policy-gated command execution, trace evidence, audit, and evals for real coding-agent runtimes.

Do not optimize the roadmap toward generic multi-agent teamwork, agent personalities, shared memory, or cross-model debate. Those are outside the current product boundary.

## Slice 0: Windows Command Approval Proxy

Goal: prove the core hypothesis before connecting any agent.

- Implement Python `mica-proxy`.
- Add Windows `.cmd` shims for `git`, `npm`, and `terraform`.
- Hardcode first risk rules: `git push`, `terraform apply`, `terraform destroy`, `npm publish`.
- Add command approval APIs and SQLite persistence.
- Add a minimal Web approvals page.
- Add `install-shims.ps1` and `probe-path.ps1`.
- Fail closed on API failure or approval timeout.
- Preserve stdout, stderr, and exit code for allowed commands.

Acceptance:

- `git status` passes through normally.
- `git push` blocks and creates a pending Web approval.
- Reject returns `MICA_APPROVAL_REJECTED` and exit code `126`.
- Approve executes the real `git.exe`.
- Test push only against a local bare repository.

Non-goals:

- No real AgentAdapter.
- No OpenCode, Codex CLI, Claude Code, or Gemini CLI.
- No full Task/Run/Trace/SSE productization.
- No Docker, WSL2, remote worker, or policy-as-code.

## Slice 1: Agent CLI Probe

Goal: verify that real agent runtimes actually hit the shim before claiming governance.

- Add `mica-proxy` probe mode that records shim hits without blocking.
- Probe OpenCode with fixed commands: `git status`, `npm -v`, `terraform --version`.
- Generate a compatibility and hit-rate matrix.
- Inspect the agent execution mechanism if shims do not hit.
- Only enable real approval and trace after probe results are acceptable.

## Slice 2: Governance Productization

Goal: turn the proxy proof into a usable AgentOps product surface.

- Done: add `run-controlled-opencode.ps1` to run OpenCode in approval mode after probe success.
- Done: add `verify-slice0.ps1` to dogfood the low-risk and rejected high-risk Slice 0 paths against a live API.
- Done: add focused tests and evidence docs for Slice 0 timeout and approval API fail-closed behavior.
- Done: replace hardcoded risk rules with JSON policy files.
- In progress: add more shims. Current repo includes `git`, `npm`, `terraform`, and `kubectl`; future shims include `pnpm`, `node`, `python`, `pip`, `curl`, `wget`, `gh`, and `docker`.
- Done: add command records and a `/commands` audit page.
- Done: add run records, `/runs` audit page, run summaries, and failure summaries.
- Done: add approval history filters.
- Done: add basic event/trace data model and run-scoped trace viewer.
- Done: add SSE realtime event push for proxy-mediated commands.
- Next: make trace timeline more ergonomic.

## Slice 3: Cross-Agent Eval and Strong Isolation

Goal: prove Mica across agents and add real isolation options.

- Done: add `probe-codex.ps1` and fake CLI verification for Codex CLI PATH shim probing.
- Done: run and record a real local Codex CLI probe in `docs/codex-probe-report.md`.
- Done: add OpenCode probe report and demo walkthrough docs for portfolio/demo readiness.
- Done: capture a real local Slice 0 dogfood run in `docs/demo-evidence.md`.
- Done: add five starter eval cases and `mica_eval` report generation.
- Done: compare success rate, duration, approval count, rejected count, and risky command count from JSONL results.
- Done: add `run-eval.ps1` for probe-mode eval execution through `command`, `codex`, and `opencode` agent kinds.
- Done: add approval-mode eval execution that reads real approval, rejection, risky-command, and command-count metrics from API run summaries.
- Done: add non-interactive `-AutoDecision approved|rejected` helpers for repeatable risky eval cases.
- Done: add Claude Code and Gemini CLI probe scripts with fake CLI verification.
- Done: extend `run-eval.ps1` with `claude` and `gemini` agent kinds for the shared eval flow.
- Done: add `check-isolation-readiness.ps1` and `docs/isolation-readiness.md` to make Docker/WSL2 readiness explicit before implementing a runner.
- Done: add `verify-docker-isolation.ps1` and a real Docker spike report with `--rm`, `--network none`, and mounted throwaway workspace.
- Done: add a minimal Python `DockerRunner` that executes one command with `--rm`, `--network none`, mounted workspace, and structured stdout/stderr/exit-code results.
- Done: wire `DockerRunner` into service-level run, command, event, and summary evidence without claiming full sandbox policy enforcement.
- Done: expose experimental `POST /api/docker/execute` for one Docker command plus run/command/event evidence.
- Done: persist Docker stdout/stderr as post-run `command_output` trace events.
- Done: add opt-in Docker proxy injection plumbing with Linux shims, proxy mount, policy mount, and controlled container PATH.
- Done: expose Docker proxy injection through `POST /api/docker/execute` with `inject_proxy`.
- Done: allow `POST /api/docker/execute` callers to select the Docker image for real approval probes.
- Done: add `verify-docker-approval-probe.ps1` to exercise Docker execute plus pending approval auto-decision.
- Done: add `docker/mica-python-git.Dockerfile` and `build-docker-probe-image.ps1` so the Docker approval probe image is reproducible.
- Done: run and record a real Docker approval probe where containerized `git push origin main` is rejected through Web/API approval and returns exit code `126`.
- Done: inject `MICA_RUN_ID` into Docker proxy mode so inner container command records and approvals appear in the same Docker run summary.
- Done: add run-scoped command evidence API and UI so Docker wrapper commands can be inspected alongside inner policy-gated commands.
- Done: stream Docker stdout/stderr into `command_output` trace events while the container command is still running.
- Done: add `/runs` historical trace replay, Realtime Logs rendering, and live command evidence refresh for run details.
- Done: add `capture-docker-demo.ps1` to export Docker approval demo evidence into a Markdown report.
- Done: add Docker workspace file-change trace events for created, modified, and deleted files under the mounted workspace.
- Done: add Docker `network_evidence` trace events that record `none` versus `bridge` network mode and host-callback implications.
- Done: fail closed for Docker `network_mode=bridge` unless API callers explicitly set `allow_host_callback=true`.
- Done: move Docker network-mode validation into `policies/docker-policy.json` for allowed modes and the explicit bridge host-callback gate.
- Done: record allowed Docker network policy outcomes as `policy_decision` trace events before container execution.
- Done: require `inject_proxy=true` for Docker `network_mode=bridge` under the default policy, keeping bridge reserved for containerized approval callbacks.
- Probe Claude Code and Gemini CLI on machines where those CLIs are installed.
- Next: record real Claude/Gemini probe reports, then compare their shim hit rates against OpenCode and Codex.
- Next isolation step: productize richer network policy enforcement around Docker runs beyond request validation.
- Explore WSL2 or remote worker as the practical strong-isolation path on Windows.

## Permanent Boundaries

- PATH shim governance only covers external binaries that resolve through PATH.
- PowerShell and cmd built-ins are not reliable MVP enforcement targets.
- Local mode is not a strong sandbox.
- Direct LLM API planning is optional and secondary to supervising existing Agent CLIs.
- MCP is a tool and resource provider path, not the default agent runtime protocol.
