# Security research escalation policy

Status: policy implemented and exercised offline. Every explicit research request creates a pending owner approval; nothing is sent until the owner approves.

## Decision policy

| Situation | Bridge action |
| --- | --- |
| Explicit request with matching trusted scope and passive work | Persist `pending_approval`; send nothing to DeepSeek until approved |
| Permission denial or safety boundary | Record boundary; no rerouting, retry, or privilege expansion |
| Malformed/oversized envelope, invalid paths, unavailable trusted policy | No dispatch; record actionable local error |
| Active scanning, exploit execution, autonomous target interaction | Unsupported in v1, even if approved |

For a permission/safety boundary, the owner may define a separate, narrower permitted research task. Approval cannot replay the denied operation or override a missing capability. Pending approval permits only supported passive analysis after all other checks succeed.

## Trusted authorization

A human-maintained scope registry is mandatory for research; agent self-classification alone cannot establish authorization. Each scope identifies repository/target, permitted passive activities, outbound file rules, expiration, budgets, and policy version. `allow_inline` and `sensitive` are still accepted in existing registries but have no effect, because every request already needs approval. Broad wildcard scopes are rejected initially.

Store this registry outside the repository and worker workspace with owner-only write permissions. Project `.claude/security-research-state.json` can contain objective, attempted approaches, verified findings, blockers, hypotheses, and next experiments, but is untrusted context. It cannot authorize a task or change scope.

An approval binds the exact canonical task hash, scope ID/version, outbound context content hashes, model/limits, and expiry. Re-read and validate before dispatch; changed bytes, changed scope, expired approval, or a new action require a new decision. Model output cannot approve itself. The local owner interface is the trust boundary; software running as the same owner is outside this protection model.

## Required test scenarios

Offline fixtures must cover absent/expired scope, permission and safety boundaries, traversal/symlink escapes, forged task revisions, stale approval, changed outbound bytes, and database failure. Assert both the state transition and that no forbidden DeepSeek call occurred.

Test approvals separately: rejection, expiry, hash mismatch, policy change, revalidation on dispatch, and inability to approve from MCP or a worker. Research result tests must keep inference separate from verified evidence and preserve missing usage as unknown.
