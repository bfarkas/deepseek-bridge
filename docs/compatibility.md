# Compatibility evidence

Recorded 2026-11-01. Offline results and public documentation checks are distinguished from live integrations. Do not treat fixture success as real OpenCode or Claude Code certification.

| Component | Selected/tested version | Evidence and limits |
| --- | --- | --- |
| Python | 3.14.7 locally; requires >=3.12 | Full local suite; CI matrix defines 3.12/3.14 on macOS/Linux, not yet run here |
| Git | 2.54.0 (Apple Git-157) | Fixture worktrees, hooks disabled, dirty original checkout preserved, new/deleted/binary patches checked with git apply |
| Anthropic SDK | 0.72.0 | Pinned; httpx MockTransport exercises messages, 429 retries, timeout without uncertain-charge retry |
| FastMCP | 2.13.0 | Pinned; in-process client and real stdio server subprocess initialization/tool listing tested |
| Pydantic | 2.12.3 | Versioned strict-extra contracts and schemas tested |
| psutil | 7.1.3 | Host PID creation-time/UID/group checks; timeout/cancellation fixtures |
| uv | 0.13.6 used for lock | uv.lock records all transitive versions; no paid calls during resolution |
| Claude Code | 2.1.309 | Installed; subscription login and real user-scoped stdio MCP connection passed |
| OpenCode | opencode v2.2.5 (Homebrew) | Real standalone debug config, headless JSON events, native write in disposable Git repo, and process-group timeout checked with local mock provider; no live DeepSeek request |
| Host toolchain | CPython + pytest 8.4.2 | Independent verification in fixture worktree; other local toolchains untested |
| DeepSeek | Endpoint documented; live response untested | SDK pointed explicitly at direct endpoint; no credential required for offline suite |

## API capability decisions

The [DeepSeek Anthropic compatibility documentation](https://api-docs.deepseek.com/guides/anthropic_api/) documents the direct endpoint and current model names. The adapter accepts `deepseek-flash` and `deepseek-v4-pro`, sends non-thinking text requests, and preserves complete assistant content blocks for continuation. Every explicit effort setting currently returns `unsupported_capability`; exact mappings require a live spike before enabling. No silent effort downgrade occurs.

The API documentation warns that some integrations can exceed requested output tokens. Byte, deadline, and concurrency enforcement reduce spending; token limits cannot guarantee the final bill. Missing usage stays null. Only explicit HTTP 429 rejections retry (at most twice); timeouts, connection failures, and server errors remain charge-ambiguous and are not silently replayed.

## OpenCode gate

Follow the [CLI](https://opencode.ai/docs/cli/), [configuration](https://opencode.ai/docs/config/), and [permissions](https://opencode.ai/docs/permissions/) references. Record exact `--version`, sanitized `debug config`, headless `run --format json` events, model IDs, usage, local toolchain access, and process cancellation from a disposable trusted repository. Both synthetic harness fixtures and sanitized real v2.2.5 binary captures are identified in tests/fixtures. The installed v2 requires `--standalone` to avoid attaching to a shared managed service and returns configuration-source documents rather than the older merged object. The adapter validates exact approved sources and normalized permissions. Native write succeeded using canonical macOS paths; `/tmp` aliases can trigger external-directory denial, which is retained. The observed event stream omits model IDs, so actual model remains null. Token counters reflect the local mock response; OpenCode cost fields are not treated as bills. The adapter rejects effective plugins/MCP/custom agents/commands/instructions, denies shell/external directories, and allows native read/edit/glob/grep. Trusted preparation and verification argv execute separately. If the actual pinned executable cannot satisfy these checks, leave the worker disabled and adapt it with new fixtures; do not weaken checks to claim compatibility.

## Opt-in paid smoke

```sh
# No live calls occur unless both controls are explicitly set.
DEEPSEEK_BRIDGE_LIVE=1 uv run python scripts/live_smoke.py --allow-paid-call
```

This sends a tiny explicit consultation with a 32-token output limit and prints only model/usage/status. It requires a configured private credential. No live smoke was run during implementation.

## Remaining release evidence

Live DeepSeek consultation/worker/research, worker plus verification process-group behavior across runner crash, service-manager removal, and Linux service installation remain unrun. The macOS runner install/heartbeat and private-file/Keychain loading are implemented; no existing dedicated DeepSeek Keychain item was found, and an empty mode-600 credential file was provisioned. Detached descendants and processes whose identity cannot be proven require manual recovery. Windows is unsupported. Account permissions are the execution boundary; host fixtures establish intended behavior, not malicious-process containment.
