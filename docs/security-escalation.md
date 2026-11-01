# Security research escalation policy

Status: proposed escalation and authorization policy. Default: automatic escalation for eligible technical blockers; owner approval for sensitive or ambiguous cases.

## Decision policy

| Situation | Bridge action |
| --- | --- |
| Completed task or no structured marker | No escalation |
| Technical blocker/expertise gap, matching trusted scope, passive work, approved outbound context | Queue automatically, once per task revision |
| Sensitive scope, uncertain authorization, ambiguous classification, new context exposure | Persist `pending_approval`; send nothing to DeepSeek |
| Permission denial or safety boundary | Record boundary; no rerouting, retry, or privilege expansion |
| Tool error without a task envelope | Record telemetry only |
| Claude API failure | Record resumable failure; do not infer a task from the API error text |
| Malformed/oversized envelope, invalid paths, unavailable trusted policy | No dispatch; record actionable local error |
| Active scanning, exploit execution, autonomous target interaction | Unsupported in v1, even if approved |

For a permission/safety boundary, the owner may define a separate, narrower permitted research task. Approval cannot replay the denied operation or override a missing capability. Pending approval permits only supported passive analysis after all other checks succeed.

## Trusted authorization

A human-maintained scope registry is mandatory for automatic escalation; agent self-classification alone cannot establish authorization. Each scope identifies repository/target, permitted passive activities, data sensitivity and outbound file rules, expiration, budgets, and policy version. Broad wildcard scopes are rejected initially.

Store this registry outside the repository and worker workspace with owner-only write permissions. Project `.claude/security-research-state.json` can contain objective, attempted approaches, verified findings, blockers, hypotheses, and next experiments, but is untrusted context. It cannot authorize a task or change scope.

An approval binds the exact canonical task hash, scope ID/version, outbound context content hashes, model/limits, and expiry. Re-read and validate before dispatch; changed bytes, changed scope, expired approval, or a new action require a new decision. Model output cannot approve itself. The local owner interface is the trust boundary; software running as the same owner is outside this protection model.

## Hook handling

Use `Stop` and `SubagentStop` to parse explicit agent handoffs. Observe `PostToolUseFailure` without interpreting ordinary failures as authorization. `PermissionDenied`, where supported, records auto-mode denials only; it does not cover every denial path, so the bridge must enforce scope independently. Do not request a denied tool retry.

`StopFailure` is telemetry-only in the initial release. A later opt-in recovery path may enqueue an already persisted, owner-authorized handoff; it must not use the API error as a task. Hook outputs do not revive an unavailable Claude session. Inspect installed Claude Code support before registering optional events. See [official hook semantics](https://code.claude.com/docs/en/hooks).

Hooks perform bounded validation and local persistence only, targeting under one second. Database/parse errors must not trigger network calls or broad continuation loops. Return event-appropriate output; use empty success output unless there is a specific supported notification. Do not block `Stop` repeatedly to poll a job. Honor continuation guards and deduplicate across orchestrator and subagent events. Claude retrieves results explicitly when still available or after resume.

## Required test scenarios

Offline fixtures must cover eligible technical blockers, expertise gaps, sensitive pending jobs, absent/expired scope, permission and safety boundaries, no marker, malformed JSON, oversized input, traversal/symlink escapes, duplicate Stop/SubagentStop delivery, concurrent duplicate claims, forged task revisions, stale approval, changed outbound bytes, API-error text, database failure, and recursive stop handling. Assert both the state transition and that no forbidden DeepSeek call occurred.

Test approvals separately: rejection, expiry, hash mismatch, policy change, revalidation on dispatch, and inability to approve from MCP or a worker. Research result tests must keep inference separate from verified evidence and preserve missing usage as unknown.
