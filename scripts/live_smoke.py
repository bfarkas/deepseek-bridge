"""Explicitly opt-in paid smoke; never part of offline CI."""

import argparse
import json
import os

from deepseek_bridge.contracts import Ask
from deepseek_bridge.service import Service
from deepseek_bridge.settings import load_settings

parser = argparse.ArgumentParser()
parser.add_argument("--allow-paid-call", action="store_true")
args = parser.parse_args()
if not args.allow_paid_call or os.environ.get("DEEPSEEK_BRIDGE_LIVE") != "1":
    parser.error("Set DEEPSEEK_BRIDGE_LIVE=1 and pass --allow-paid-call to permit billing")
result = Service(load_settings()).ask(Ask(task="Reply with the word ready.", max_output_tokens=32))
print(json.dumps({"status": result["status"], "usage": result["usage"]}, indent=2))
