"""Rucio client factory: abstracts how the rucio.Client is obtained per-request."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context
    from rucio.client import Client


class RucioClientFactory(ABC):
    """Returns the rucio.Client appropriate for the current request/session."""

    @abstractmethod
    def get_client(self, ctx: Context) -> Client: ...

    def close(self) -> None:
        """Release any cached clients or resources."""


class EnvBasedClientFactory(RucioClientFactory):
    """Stdio-mode factory: wraps a single Client built from process env vars."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get_client(self, ctx: Context) -> Client:
        return self._client
