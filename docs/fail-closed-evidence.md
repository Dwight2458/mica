# Fail-Closed Evidence

This file records the automated evidence for Mica's Slice 0 fail-closed behavior.

## Requirement

High-risk commands must not execute unless Mica receives an approval decision.

Required outcomes:

- pending approval timeout returns a non-zero exit code
- unavailable approval API returns a non-zero exit code
- the real command is not executed in either case
- timeout and failure are visible to the caller

## Automated Tests

The evidence lives in `apps/api/tests/test_mica_proxy.py`.

Run only the fail-closed checks:

```powershell
cd apps\api
uv run pytest tests/test_mica_proxy.py -k "times_out or fails_closed"
```

Expected result:

```text
2 passed
```

## Covered Cases

### Pending Approval Timeout

Test:

```text
test_proxy_times_out_pending_approval_without_executing_command
```

Evidence:

- command: `git push origin main`
- fake approval API keeps returning `pending`
- proxy returns exit code `124`
- command record is finished with status `timeout`
- real command execution is guarded by a test stub that fails the test if called

### Approval API Unavailable

Test:

```text
test_proxy_fails_closed_when_approval_api_is_unavailable
```

Evidence:

- command: `git push origin main`
- fake approval API raises `URLError`
- proxy returns exit code `125`
- real command execution is guarded by a test stub that fails the test if called

## Interpretation

This proves Mica's local command proxy fails closed for these two Slice 0 failure modes. It does not turn Local mode into a strong sandbox. A process can still bypass PATH shims with absolute executable paths, shell built-ins, or direct library calls.
