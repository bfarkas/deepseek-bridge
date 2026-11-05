# Setup, review, and recovery

## Private configuration and data

Install with `uv sync --frozen`, or `uv tool install . --python 3.12` for a standalone launcher. Copy config.example.toml to `~/.config/deepseek-bridge/config.toml`, mode 600, outside repositories and worker directories. Credentials load from `DEEPSEEK_API_KEY`, then the private JSON file configured by top-level `credentials_file` (default `~/.config/deepseek-bridge/credentials.json`), then a dedicated macOS Keychain generic-password item with service `deepseek-bridge` and account `DEEPSEEK_API_KEY`. The Passwords app is not integrated. The JSON file must be a regular, owner-only file (mode 600), containing only `{"DEEPSEEK_API_KEY": "your-key"}`; never put its value in the TOML file, MCP settings, service files, or command arguments. Credentials are read at request time, so filling the file needs no restart. The direct provider constructs its own SDK client and never modifies Claude authentication environment variables or files.

Register repository aliases and trusted verification argv in that configuration. Runtime state defaults to `~/.local/state/deepseek-bridge`, mode 700. SQLite, consultations, content snapshots, and artifacts contain private code/findings. Parents should also be private. Keep state outside Git; do not commit keys, prompts, live payloads, or runtime artifacts. `DEEPSEEK_BRIDGE_CONFIG` or global `--config PATH` chooses another configuration.

`doctor` is read-only except for initializing private local storage. It checks configuration/schema, credential presence, candidate model IDs, runner heartbeat, and executable presence. A stopped runner returns nonzero with an actionable start instruction. Missing worker/live compatibility is reported separately; doctor is not proof of live API or host-worker compatibility.

## Separate runner and services

Run `deepseek-bridge runner` in its own terminal during development. `runner --once` drains one bounded batch and exits. The runner uses an exclusive file lock, transactional SQLite claims, heartbeats, repository/shared-resource scheduling, and a shared provider/worker concurrency limit of one by default (maximum three). MCP only enqueues jobs. It never spawns detached workers. Consultations remain synchronous and need no runner.

After recording compatibility evidence, `deepseek-bridge --config /absolute/private/config.toml service install` installs a user launchd agent on macOS or systemd user service on Linux. `service remove` stops/removes only that service and preserves data. macOS launchd installation and runner heartbeat were verified on the development host; removal and Linux systemd remain untested on real hosts. The private credential file also works for the service; credentials are not written to service files. Use an absolute virtualenv launcher and ensure its configured PATH includes approved toolchains. Service installation cannot fix missing toolchains or credentials automatically.

SIGINT/SIGTERM persists cancellation for running jobs and waits for bounded execution to stop. Provider cancellation waits for an in-flight request's configured timeout and may still incur billing. Crash restart stops processes only when PID/start time/UID/group ownership matches, then marks unfinished jobs interrupted. It never reexecutes them automatically. Ambiguous process ownership stops runner startup for manual inspection; never kill a PID merely because its number was recorded. A crash between process creation and ownership persistence remains a small recovery gap; inspect host processes before retrying uncertain work.

## Coding workflow

Leave `[worker].enabled=false` until docs/compatibility.md gates pass. Set `expected_version` to the exact tested executable output, a private worktree root if desired, and `compatibility_verified=true`. Shell tools are denied to the model; dependency preparation and verification use owner-configured argv separately with credential-filtered environments. This is an intentionally conservative host adapter, not a sandbox. Caches/services shared between jobs must be named in repository `shared_resources`.

Example request file (pass with `jobs start --request request.json`; MCP uses the same object under `request`):

```json
{"schema_version":"1.0","repository":"example-project","task":"Fix the parser","acceptance_criteria":["Regression test passes"],"verification_profile":"approved-tests","base_ref":"HEAD","client_request_id":"parser-fix-1","limits":{"timeout_seconds":1800,"max_output_tokens":8000}}
```

Use `jobs list`, `jobs status ID`, `jobs result ID`, and `jobs cancel ID`. `jobs retry ID` explicitly creates a new coding attempt linked to the terminal original and preserves its immutable base SHA; research requires a new owner-created task revision. Review the independently collected binary-capable patch, base SHA, changed tests, verification argv/exit/log/workspace hashes, actual model if reported, and nullable usage. Pipeline completion differs from verification success. Verification commands may execute worker-modified code/tests, so passing is evidence to review, not a security guarantee. `jobs review ID accepted|rejected` records the owner's outcome. Integrate patches separately and rerun tests after integration. There is no automatic commit/merge/push/deploy.

`jobs export ID /new/private/destination` verifies artifact checksums before export. `jobs delete ID` only accepts terminal jobs and bridge-owned worktrees that Git can remove without force. Dirty worktrees are retained: review/export, then archive or commit changes manually in that bridge worktree before deletion. Cleanup never force-resets the original checkout. If a bridge branch has commits, integrate/archive them before `branch -d` can succeed.

## Trusted research and approval

Add top-level `scope_registry="/absolute/private/scopes.json"` **before** any TOML table. The owner maintains this mode-600 JSON file outside all repositories/worktrees, with a parent not writable by group/others. Example (replace expiry with a future Unix timestamp and session with the actual session):

```json
{"scopes":{"parser-review":{"repository":"example-project","version":"1","expires":1794000000,"files":["src/parser.py"],"allow_inline":false,"sensitive":false,"passive_activities":["passive_analysis"],"max_output_tokens":4000,"timeout_seconds":120}},"tasks":{"parser-task":{"revision":1,"scope_id":"parser-review","session_id":"actual-session","objective":"Explain parser failure"}}}
```

`research --request handoff.json --session-id actual-session` creates a pending proposal. Use the contract in docs/contracts.md. `approvals show ID` displays the exact snapshot, action, scope fingerprint, limits/hash, and expiry. `approvals approve ID --request-hash HASH` requires an interactive owner terminal and typing `approve`. `approvals reject ID --request-hash HASH` rejects. MCP has no approval tool. Revalidation at dispatch rejects changed bytes, model, scope, revision, expiry, or hash. Active research and permission/safety rerouting remain unsupported even with approval.

`.claude/security-research-state.json` is untrusted text: include it explicitly through context only if scope permits. It never grants permission.

## Rollback

To roll back, run `claude mcp remove deepseek-bridge`, stop/remove its user runner service, and leave private state intact. Consultations can be disabled by removing the credential from all configured sources. No global Claude authentication setting needs changing.

## Retention and budgets

Run `prune` periodically from the owner CLI; retention defaults to 30 days. Consultations expire, terminal jobs with safely removable worktrees are deleted, dirty jobs remain for review, and old unreferenced artifact files are cleaned. Export before deletion when evidence matters. SQLite deletion is logical, not a secure wipe; protect the disk and backups.

Time/output/context/concurrency limits are enforced locally. Worker token limits are observed from completed step events and may overshoot by an in-flight step. The bridge records token usage, not dollar cost. Cache read/creation counters and absent test counts stay unknown when unreported. Never retry an interrupted/bill-ambiguous job without reviewing its artifacts and starting an explicit new attempt.

## Local macOS setup recorded 2026-11-01

`scripts/setup_local.py` installs this checkout's virtualenv launcher, creates private configuration/empty credentials/empty scopes without replacing existing files, and starts the launchd runner. It assumes Homebrew OpenCode 2.2.5 at `/opt/homebrew/bin/opencode`; it does not certify another installed version. The launcher depends on this checkout and `.venv` remaining in place.

On the development host, Claude Code 2.1.309 was installed and subscription sign-in completed, the user-scoped MCP connection passed, and the verified OpenCode pin was enabled. No owner scopes/tasks were supplied for research. The credential file is an empty placeholder until the owner fills it locally. No paid DeepSeek calls were made. Coding jobs use committed Git bases; uncommitted implementation files in the original checkout are not copied into a job. The registered test profile uses pytest's `pythonpath=src` so imports come from the job worktree rather than the editable installation.
