"""Read auth-relevant fields from the [client] section of rucio.cfg."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class RucioCfg:
    """Subset of rucio.cfg [client] fields used by server startup and the OAuth bridge."""

    rucio_host: str
    auth_host: str
    account: str
    auth_type: str | None
    oidc_audience: str
    oidc_scope: str
    oidc_issuer: str

    @classmethod
    def from_path(cls, path: Path) -> RucioCfg:
        """Parse *path* and return a :class:`RucioCfg` from its ``[client]`` section."""
        cp = configparser.ConfigParser()
        cp.read(path)
        c = cp["client"]
        return cls(
            rucio_host=c["rucio_host"],
            auth_host=c["auth_host"],
            account=c.get("account", ""),
            auth_type=c.get("auth_type") or None,
            oidc_audience=c.get("oidc_audience", "rucio"),
            oidc_scope=c.get("oidc_scope", "openid profile offline_access"),
            oidc_issuer=c.get("oidc_issuer", ""),
        )
