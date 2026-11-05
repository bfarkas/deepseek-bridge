"""Install the owner's local launcher/config and supervise the runner on this host.

Run explicitly with the project virtualenv Python. Existing private files are preserved.
"""

import json
import os
import shlex
from pathlib import Path

from deepseek_bridge.services import NAME, configure
from deepseek_bridge.settings import private_dir


def create(path: Path, content: str, mode: int = 0o600) -> bool:
    if path.exists():
        return False
    with path.open("x") as stream:
        os.chmod(path, mode)
        stream.write(content)
    return True


def main() -> None:
    os.umask(0o077)
    repo = Path(__file__).absolute().parents[1]
    home = Path.home()
    config_root = private_dir(home / ".config/deepseek-bridge")
    state = private_dir(home / ".local/state/deepseek-bridge")
    bin_root = home / ".local/bin"
    bin_root.mkdir(parents=True, exist_ok=True)
    executable = repo / ".venv/bin/python"
    if not executable.exists():
        raise SystemExit("Run uv sync --frozen in this checkout first")
    credential_file = config_root / "credentials.json"
    create(credential_file, json.dumps({"DEEPSEEK_API_KEY": ""}, indent=2) + "\n")
    create(config_root / "scopes.json", json.dumps({"scopes": {}, "tasks": {}}, indent=2) + "\n")
    config = config_root / "config.toml"
    config_text = (repo / "config.example.toml").read_text()
    config_text = (
        "scope_registry = " + json.dumps(str(config_root / "scopes.json")) + "\n"
        "credentials_file = " + json.dumps(str(credential_file)) + "\n\n" + config_text
    )
    config_text = config_text.replace(
        'executable = "opencode"', 'executable = "/opt/homebrew/bin/opencode"'
    )
    config_text = config_text.replace(
        '# expected_version = "YOUR_VERIFIED_VERSION"', 'expected_version = "opencode v2.2.5"'
    )
    config_text += (
        "\n[repositories.deepseek-bridge]\npath = " + json.dumps(str(repo)) + "\n"
        'verification_profile = "bridge-tests"\n'
        "[profiles.bridge-tests]\ncommands = "
        + json.dumps(
            [[str(executable), "-I", "-B", "-m", "pytest", "-q", "-o", "pythonpath=src"]]
        )
        + "\n"
        "version_commands = " + json.dumps([[str(executable), "--version"]]) + "\n"
    )
    create(config, config_text)
    wrapper = bin_root / "deepseek-bridge"
    script = (
        "#!/bin/sh\n"
        'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:'
        '/usr/sbin:/sbin${PATH:+:$PATH}"\n'
        "exec " + shlex.quote(str(executable)) + ' -m deepseek_bridge "$@"\n'
    )
    if wrapper.exists() and wrapper.read_text() != script:
        raise SystemExit("Existing launcher differs; review it before replacing")
    create(wrapper, script, 0o700)
    os.environ["PATH"] = str(bin_root) + os.pathsep + os.environ.get("PATH", os.defpath)
    service_file = home / "Library/LaunchAgents" / (NAME + ".plist")
    if not service_file.exists():
        configure(config)
    print(
        json.dumps(
            {
                "launcher": str(wrapper),
                "configuration": str(config),
                "credential_file": str(credential_file),
                "state": str(state),
                "service": str(service_file),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
