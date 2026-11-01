# Claude Code integration and operations

Status: intended installation workflow after implementation; these commands are not runnable in this scaffold.

## Authentication and installation

Keep normal Claude Code subscription login. Do not set `ANTHROPIC_BASE_URL`, replace Claude credentials, or route the Claude session through DeepSeek. Only the bridge/provider client uses the configured DeepSeek endpoint and `DEEPSEEK_API_KEY`. Use a private environment or an operating-system credential-store launcher; do not include the key in MCP command arguments or tracked settings.

The intended executable will register as a user-scoped local stdio server, consistent with [Claude's MCP documentation](https://code.claude.com/docs/en/mcp):

```sh
# Planned commands after package implementation and installation
claude mcp add --scope user --transport stdio deepseek-bridge -- /absolute/path/to/deepseek-bridge serve
deepseek-bridge doctor
```

Check `/mcp` inside Claude. Start the separately installed runner through the configured service manager before asynchronous jobs; `doctor` reports runner health, schema/config validity, API credential presence, model compatibility, and sandbox availability without printing keys. It must not make paid calls unless explicitly requested.

## Delegation instructions

Use MCP directly from the main orchestrator first. An optional native Claude `deepseek-coordinator` subagent can call the same tools; it remains a Claude agent and adds Claude usage. Select an available coordinator model during setup rather than hard-coding a historical alias.

The trusted Claude instructions should say: provide explicit context and acceptance criteria, omit secrets, keep final decisions with Claude, inspect actual patches and verification evidence, and treat model findings as unverified until checked. Independent coding tasks must avoid overlap with active changes. No worker automatically merges, pushes, or deploys.

For research escalation, tell agents to emit the [structured marker](contracts.md) only for a known task and scope. State the blocker accurately; never relabel a permission/safety boundary as technical uncertainty. Do not expose approval tools to agents.

## Hooks

After implementation, merge generated hook entries into the owner's existing settings; do not overwrite the file. Start with `Stop` and `SubagentStop` invoking an absolute launcher path with `hook`. Add optional telemetry events only after compatibility checks. Paths with spaces require platform-correct quoting in generated command strings.

Validate `/hooks`, capture a sanitized event fixture, and exercise a controlled technical blocker. Verify that pending approval sends no data and duplicates enqueue once. The hook persists the job and returns promptly. The runner works independently; the active or resumed Claude session explicitly retrieves the result rather than being promised automatic resumption.

## Review, recovery, and uninstall

For coding jobs, inspect `changes.patch`, altered tests, base SHA, verification command/exit status, and unresolved issues. Integrate separately through the owner's normal merge/cherry-pick workflow. If the destination advanced, handle conflicts explicitly and rerun relevant verification. Preserve worktrees until review, then use bridge cleanup; never remove arbitrary paths or force-reset the user's checkout.

When the provider fails, show a sanitized retryable error and usage uncertainty. When the runner stops, preserve queued jobs and reconcile interrupted execution before retrying. Disable only bridge hook entries, unregister only this MCP server, and stop/remove only its runner service to uninstall. Keep or explicitly delete private state/artifacts according to the owner's choice. No global settings or repository deletion is implied.
