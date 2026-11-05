# Direct orchestrator usage

Register the local stdio server with an absolute installed launcher (see README.md). Keep Claude's subscription login unchanged. Ask Claude to call `deepseek_review` with `request.task` and explicitly chosen `request.context.files`/`diff`/`text`, inspect returned findings/usage, and verify suggestions itself.

Coding tools queue jobs only when the owner enables the verified host adapter. Retrieve `deepseek_job_status` and `deepseek_job_result`; review patch, base SHA, changed tests, and independently observed verification logs. Integrate separately. Research proposals require an owner-created scope/task revision and local interactive approval; never instruct an agent to approve its own work.

An optional native Claude coordinator can call these same tools and adds normal Claude usage. Choose its model from your installed Claude's available models; no DeepSeek model name in Claude subagent configuration establishes provider routing by itself.
