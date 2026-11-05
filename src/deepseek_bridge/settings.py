import os
import stat
import tomllib
from pathlib import Path

from pydantic import Field, model_validator

from .contracts import StrictModel
from .errors import BridgeError


class DeepSeek(StrictModel):
    base_url: str = "https://api.deepseek.com/anthropic"
    api_key_env: str = "DEEPSEEK_API_KEY"
    consultant_model: str = "deepseek-flash"
    review_model: str = "deepseek-v4-pro"
    research_model: str = "deepseek-v4-pro"

    @model_validator(mode="after")
    def endpoint(self) -> "DeepSeek":
        if self.base_url != "https://api.deepseek.com/anthropic":
            raise ValueError("Only the direct HTTPS DeepSeek endpoint is supported")
        return self


class Consultant(StrictModel):
    max_files: int = Field(default=20, ge=1, le=20)
    max_input_bytes: int = Field(default=200000, ge=1, le=200000)
    max_output_tokens: int = Field(default=8000, ge=1, le=8000)
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class Jobs(StrictModel):
    max_concurrent: int = Field(default=1, ge=1, le=3)
    max_concurrent_limit: int = Field(default=3, ge=1, le=3)
    default_timeout_seconds: int = Field(default=1800, ge=1, le=3600)
    max_timeout_seconds: int = Field(default=3600, ge=1, le=3600)

    @model_validator(mode="after")
    def bounds(self) -> "Jobs":
        if self.max_concurrent > self.max_concurrent_limit:
            raise ValueError("Concurrency exceeds configured limit")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("Default timeout exceeds maximum")
        return self


class Worker(StrictModel):
    enabled: bool = False
    executable: str = "opencode"
    expected_version: str | None = None
    model: str = "deepseek/deepseek-v4-pro"
    worktree_root: Path | None = None
    max_output_bytes: int = Field(default=2000000, ge=1000, le=10000000)
    # Set only after recording real effective-config and headless-event evidence.
    compatibility_verified: bool = False


class Storage(StrictModel):
    state_dir: Path = Field(default_factory=lambda: Path.home() / ".local/state/deepseek-bridge")
    database_filename: str = "bridge.sqlite3"
    retention_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def filename(self) -> "Storage":
        if Path(self.database_filename).name != self.database_filename:
            raise ValueError("Database filename must be a basename")
        return self


class Repository(StrictModel):
    path: Path
    verification_profile: str
    preparation_profile: str | None = None
    shared_resources: list[str] = Field(default_factory=list)


class Profile(StrictModel):
    commands: list[list[str]] = Field(min_length=1)
    environment: dict[str, str] = Field(default_factory=dict)
    version_commands: list[list[str]] = Field(default_factory=list)

    @model_validator(mode="after")
    def argv(self) -> "Profile":
        if any(
            not command or not command[0] or any("\x00" in arg for arg in command)
            for command in [*self.commands, *self.version_commands]
        ):
            raise ValueError("Profiles require nonempty executable argv")
        return self


class Settings(StrictModel):
    deepseek: DeepSeek = Field(default_factory=DeepSeek)
    consultant: Consultant = Field(default_factory=Consultant)
    jobs: Jobs = Field(default_factory=Jobs)
    worker: Worker = Field(default_factory=Worker)
    storage: Storage = Field(default_factory=Storage)
    repositories: dict[str, Repository] = Field(default_factory=dict)
    profiles: dict[str, Profile] = Field(default_factory=dict)
    scope_registry: Path | None = None
    credentials_file: Path = Field(
        default_factory=lambda: Path.home() / ".config/deepseek-bridge/credentials.json"
    )

    @model_validator(mode="after")
    def paths(self) -> "Settings":
        state = self.storage.state_dir.expanduser().absolute()
        worker = self.worker.worktree_root
        for repo in self.repositories.values():
            if not repo.path.is_absolute():
                raise ValueError("Repository paths must be absolute")
            if state.resolve().is_relative_to(repo.path.resolve()):
                raise ValueError("Private state must live outside repositories")
            if worker and worker.resolve().is_relative_to(repo.path.resolve()):
                raise ValueError("Worker root must live outside registered repositories")
        self.storage.state_dir = state
        return self

    def repository(self, alias: str) -> Repository:
        if alias not in self.repositories:
            raise BridgeError("out_of_scope", "Repository alias is not registered")
        return self.repositories[alias]


def load_settings(path: Path | None = None) -> Settings:
    path = path or Path(
        os.environ.get(
            "DEEPSEEK_BRIDGE_CONFIG", str(Path.home() / ".config/deepseek-bridge/config.toml")
        )
    )
    if not path.exists():
        raise BridgeError("invalid_request", "Configuration is missing; copy config.example.toml")
    settings = Settings.model_validate(tomllib.loads(path.read_text()))
    if settings.worker.enabled:
        info = path.stat()
        if path.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise BridgeError(
                "permission_boundary", "Execution configuration must be owner-private"
            )
        for repo in settings.repositories.values():
            if path.resolve().is_relative_to(repo.path.resolve()):
                raise BridgeError(
                    "permission_boundary", "Execution configuration must live outside repositories"
                )
    return settings


def private_dir(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise BridgeError("permission_boundary", "Private directory must not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise BridgeError("permission_boundary", "State directory must be owner-only (chmod 700)")
    return path
