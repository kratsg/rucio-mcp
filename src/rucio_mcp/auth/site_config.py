"""Per-site OAuth configuration loaded from bundled TOML presets."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path


_REQUIRED_KEYS = ("issuer", "jwks_uri", "audience", "scopes", "required_scopes")
_OPTIONAL_KEYS = ("authorization_endpoint", "token_endpoint", "registration_endpoint")


@dataclass(frozen=True)
class SiteAuthConfig:
    """OAuth/OIDC metadata for one experiment site (e.g. atlas, cms)."""

    issuer: str
    jwks_uri: str
    audience: str
    scopes: list[str]
    required_scopes: list[str]
    authorization_endpoint: str | None = field(default=None)
    token_endpoint: str | None = field(default=None)
    registration_endpoint: str | None = field(default=None)

    @classmethod
    def from_path(cls, path: Path) -> SiteAuthConfig:
        """Load from an arbitrary TOML file on disk."""
        data = tomllib.loads(path.read_text())
        oauth = data.get("oauth", {})
        missing = [k for k in _REQUIRED_KEYS if k not in oauth]
        if missing:
            raise ValueError(
                f"{path}: missing required oauth keys: {missing}"
            )
        return cls(
            **{k: oauth[k] for k in _REQUIRED_KEYS},
            **{k: oauth.get(k) for k in _OPTIONAL_KEYS},
        )

    @classmethod
    def from_preset(cls, site: str) -> SiteAuthConfig:
        """Load from a bundled preset (e.g. 'atlas' → data/atlas-auth.toml)."""
        from rucio_mcp.presets import PRESETS

        preset = PRESETS.get(site)
        if preset is None or preset.auth_resource is None:
            raise ValueError(f"No auth config for site {site!r}")
        text = (files("rucio_mcp.data") / preset.auth_resource).read_text()
        data = tomllib.loads(text)
        oauth = data.get("oauth", {})
        missing = [k for k in _REQUIRED_KEYS if k not in oauth]
        if missing:
            raise ValueError(
                f"atlas-auth.toml: missing required oauth keys: {missing}"
            )
        return cls(
            **{k: oauth[k] for k in _REQUIRED_KEYS},
            **{k: oauth.get(k) for k in _OPTIONAL_KEYS},
        )
