from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from utils import Scope


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    enabled: bool | None
    running: bool | None


class Backend(ABC):
    def __init__(self, scope: Scope) -> None:
        self.scope = scope

    @abstractmethod
    def create(self, name: str, wd: Path, command_parts: list[str]) -> None: ...

    @abstractmethod
    def cat(self, name: str) -> None: ...

    @abstractmethod
    def exists(self, name: str) -> bool: ...

    @abstractmethod
    def enable(self, name: str) -> None: ...

    @abstractmethod
    def disable(self, name: str) -> None: ...

    @abstractmethod
    def start(self, name: str) -> None: ...

    @abstractmethod
    def stop(self, name: str) -> None: ...

    @abstractmethod
    def remove(self, name: str) -> None: ...

    @abstractmethod
    def list_info(self) -> list[ServiceInfo]: ...
