# Role prompts

The text-only consultant system prompt and review/research JSON schema instructions are in `consultant.py`. Host coding prompts are generated in `worker.py` from validated requests. They treat model instructions as work descriptions, never as owner authorization. Passive researchers have no shell, browsing, scanning, or exploit tools; model references are unverified and model claims of verified findings are downgraded to inference.
