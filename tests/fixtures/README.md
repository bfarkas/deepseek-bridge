# Offline fixtures

`opencode-events.jsonl` and `stop.json` are **synthetic**, not captures from installed tools. The host integration tests generate a `fixture-1` fake executable, real temporary Git repositories/worktrees, and tests. SDK HTTP responses are provided by httpx MockTransport. No fixture contains a real API key, paid response, transcript, or owner scope.

Keep real sanitized installed-version hook and OpenCode captures separate and identify their source/version before claiming live compatibility. `opencode-v2.2.5-config.json` is captured from the installed Homebrew OpenCode v2.2.5 standalone debug-config command with an isolated HOME/XDG configuration. `opencode-v2.2.5-events.jsonl` is captured from the same real binary against a loopback mock OpenAI provider, successfully writing a file in a disposable Git repository. Paths are sanitized to `/fixture`; usage and costs are mock values, not paid API evidence. No actual Claude hook capture is available.
