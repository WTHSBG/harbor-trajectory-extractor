from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from harbor.utils.env import parse_bool_env_value


class NonZeroAgentExitCodeError(RuntimeError):
    pass


@dataclass
class CliFlag:
    kwarg: str
    cli: str
    type: Literal["str", "int", "bool", "enum"] = "str"
    choices: list[str] | None = None
    default: Any = None
    env_fallback: str | None = None
    format: str | None = None


@dataclass
class EnvVar:
    kwarg: str
    env: str
    type: Literal["str", "int", "bool", "enum"] = "str"
    choices: list[str] | None = None
    default: Any = None
    env_fallback: str | None = None
    bool_true: str = "true"
    bool_false: str = "false"


def _coerce_value(
    value: Any,
    type: Literal["str", "int", "bool", "enum"],
    choices: list[str] | None,
    kwarg_name: str,
) -> Any:
    if type == "bool":
        return parse_bool_env_value(value, name=kwarg_name)
    if type == "int":
        return int(value)
    if type == "enum":
        normalized = str(value).strip().lower()
        if choices and normalized not in choices:
            raise ValueError(f"Invalid value for {kwarg_name}: {value!r}")
        return normalized
    return str(value)


def with_prompt_template(fn):
    @functools.wraps(fn)
    async def wrapper(self, instruction: str, *args: Any, **kwargs: Any) -> None:
        return await fn(self, self.render_instruction(instruction), *args, **kwargs)

    return wrapper


class BaseInstalledAgent:
    """Small runtime stub for vendored Harbor post-run converters.

    It intentionally does not implement install/run behavior. The vendored
    converter classes only need constructor state, flag/env helpers, and logging
    to execute populate_context_post_run().
    """

    SUPPORTS_ATIF: bool = False
    CLI_FLAGS: ClassVar[list[CliFlag]] = []
    ENV_VARS: ClassVar[list[EnvVar]] = []

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        prompt_template_path: Path | str | None = None,
        version: str | None = None,
        extra_env: dict[str, str] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.logs_dir = Path(logs_dir)
        self.model_name = model_name
        self._version = version
        self._prompt_template_path = (
            Path(prompt_template_path) if prompt_template_path else None
        )
        self._extra_env = dict(extra_env or {})
        self.logger = logging.getLogger(f"htextract.vendor.{self.name()}")
        self.skills_dir = kwargs.pop("skills_dir", None)
        self.mcp_servers = kwargs.pop("mcp_servers", None)

        self._flag_kwargs: dict[str, Any] = {}
        for descriptor in [*self.CLI_FLAGS, *self.ENV_VARS]:
            if descriptor.kwarg in kwargs:
                self._flag_kwargs[descriptor.kwarg] = kwargs.pop(descriptor.kwarg)
        self._resolved_flags = self._resolve_flag_values()
        self._resolved_env_vars = self._resolve_env_values()

    @staticmethod
    def name() -> str:
        return "unknown"

    def version(self) -> str | None:
        return self._version

    def get_version_command(self) -> str | None:
        return None

    def render_instruction(self, instruction: str) -> str:
        return instruction

    def _resolve_raw_value(self, descriptor: CliFlag | EnvVar) -> Any:
        if descriptor.kwarg in self._flag_kwargs:
            return self._flag_kwargs[descriptor.kwarg]
        if descriptor.env_fallback and descriptor.env_fallback in os.environ:
            return os.environ[descriptor.env_fallback]
        return descriptor.default

    def _resolve_flag_values(self) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for flag in self.CLI_FLAGS:
            raw = self._resolve_raw_value(flag)
            if raw is not None:
                resolved[flag.kwarg] = _coerce_value(
                    raw, flag.type, flag.choices, flag.kwarg
                )
        return resolved

    def _resolve_env_values(self) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for env_var in self.ENV_VARS:
            raw = self._resolve_raw_value(env_var)
            if raw is None:
                continue
            coerced = _coerce_value(raw, env_var.type, env_var.choices, env_var.kwarg)
            if env_var.type == "bool":
                resolved[env_var.env] = (
                    env_var.bool_true if coerced else env_var.bool_false
                )
            else:
                resolved[env_var.env] = str(coerced)
        return resolved

    def build_cli_flags(self) -> str:
        parts: list[str] = []
        for flag in self.CLI_FLAGS:
            value = self._resolved_flags.get(flag.kwarg)
            if value is None:
                continue
            if flag.format:
                parts.append(flag.format.format(value=value))
            elif flag.type == "bool":
                if value:
                    parts.append(flag.cli)
            else:
                parts.append(f"{flag.cli} {value}")
        return " ".join(parts)

    def resolve_env_vars(self) -> dict[str, str]:
        return dict(self._resolved_env_vars)

    def _get_env(self, key: str) -> str | None:
        return self._extra_env.get(key) or os.environ.get(key)

    def _has_env(self, key: str) -> bool:
        return key in self._extra_env or key in os.environ

    async def exec_as_root(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Install/run methods are unavailable in htextract")

    async def exec_as_agent(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Install/run methods are unavailable in htextract")

