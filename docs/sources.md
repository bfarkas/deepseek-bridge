# Public references and implementation uncertainties

Status: references used for implementation. The consultant/server, durable runner, gated host worker, and research policy now exist. See [compatibility](compatibility.md) for checked versions and the distinction between fixtures and live evidence.

## Official technical references

- [DeepSeek API entry point](https://api-docs.deepseek.com/): direct API endpoints and candidate model identifiers.
- [DeepSeek Anthropic-compatible API](https://api-docs.deepseek.com/guides/anthropic_api/): provider compatibility reference; validate exact capabilities in M0.
- [Claude Code MCP](https://code.claude.com/docs/en/mcp): local tool registration.
- [OpenCode CLI](https://opencode.ai/docs/cli/): headless execution, model selection, and JSON events.
- [FastMCP](https://gofastmcp.com/getting-started/welcome): Python MCP framework.

These references inform the design; integrations have not been exercised by this scaffold. Model identifiers, effort modes and harness behavior require version-specific verification before implementation claims.

## Open engineering decisions

The supervised runner, transactional job claims, host process ownership checks, dedicated worktrees, trusted scope registry, and approval hash binding are proposed mechanisms. Their exact interfaces and platform support remain subject to the implementation milestones.

Validate host-worker process management, local toolchain access, and effective OpenCode permissions on each supported host platform. Select dependency versions, verification profiles, credential-store integrations, data-retention rules, and resource budgets through explicit compatibility checks. Numeric defaults are proposals, not measured resource requirements.
