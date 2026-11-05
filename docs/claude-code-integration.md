# Claude Code integration and operations

Status: CLI and stdio MCP are implemented; real registration/connection passed with Claude Code 2.1.309. See [operations](operations.md) for current setup and recovery.

## Authentication and installation

Keep normal Claude Code subscription login. Do not set `ANTHROPIC_BASE_URL`, replace Claude credentials, or route the Claude session through DeepSeek. Only the bridge/provider client uses the configured DeepSeek endpoint and `DEEPSEEK_API_KEY`. Use the private credential file, environment, or dedicated macOS Keychain item described in operations; do not include the key in MCP command arguments or tracked settings.

The intended executable will register as a user-scoped local stdio server, consistent with [Claude's MCP documentation](https://code.claude.com/docs/en/mcp):

```sh
# After package installation
claude mcp add --scope user --transport stdio deepseek-bridge -- /absolute/path/to/deepseek-bridge serve
deepseek-bridge doctor
```

Check `/mcp` inside Claude. Start the separately installed runner through the configured service manager before asynchronous jobs; `doctor` reports runner health, schema/config validity, API credential presence, model compatibility, and host OpenCode/toolchain availability without printing keys. It must not make paid calls unless explicitly requested.

## Delegation instructions

Use MCP directly from the main orchestrator first. An optional native Claude `deepseek-coordinator` subagent can call the same tools; it remains a Claude agent and adds Claude usage. Select an available coordinator model during setup rather than hard-coding a historical alias.

The trusted Claude instructions should say: provide explicit context and acceptance criteria, omit secrets, keep final decisions with Claude, inspect actual patches and verification evidence, and treat model findings as unverified until checked. Independent coding tasks must avoid overlap with active changes. No worker automatically merges, pushes, or deploys.

For research escalation, tell agents to submit a [handoff](contracts.md) only for a known task and scope. State the blocker accurately; never relabel a permission/safety boundary as technical uncertainty. Do not expose approval tools to agents.

## Review, recovery, and uninstall

For coding jobs, inspect `changes.patch`, altered tests, base SHA, verification command/exit status, and unresolved issues. Integrate separately through the owner's normal merge/cherry-pick workflow. If the destination advanced, handle conflicts explicitly and rerun relevant verification. Preserve worktrees until review, then use bridge cleanup; never remove arbitrary paths or force-reset the user's checkout.

When the provider fails, show a sanitized retryable error and usage uncertainty. When the runner stops, preserve queued jobs and reconcile interrupted execution before retrying. Unregister only this MCP server, and stop/remove only its runner service to uninstall. Keep or explicitly delete private state/artifacts according to the owner's choice. No global settings or repository deletion is implied.

## Host worker execution

The runner launches OpenCode directly in a dedicated Git worktree. Configure approved dependency preparation, verification commands, and any required local file/cache/service access for each repository. Source changes are reviewed in that worktree and returned as a patch; the original checkout is not the worker's working directory.

Execution uses the runner account's permissions and host networking. A worktree does not restrict access to other account-readable files or shared Git metadata. Use trusted repositories/tasks, inspect effective OpenCode configuration, and avoid concurrent jobs that conflict through shared local services. Cancellation covers verified job process groups; deliberately detached processes may need manual recovery.
