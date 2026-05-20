"""Tests for SiteAuthConfig TOML loader."""

from __future__ import annotations

import pytest


def test_load_atlas_preset():
    from rucio_mcp.auth.site_config import SiteAuthConfig

    cfg = SiteAuthConfig.from_preset("atlas")
    assert cfg.issuer == "https://atlas-auth.cern.ch/"
    assert cfg.audience == "rucio"
    assert cfg.jwks_uri == "https://atlas-auth.cern.ch/jwk"
    assert "openid" in cfg.required_scopes
    assert "openid" in cfg.scopes


def test_load_from_path(tmp_path):
    from rucio_mcp.auth.site_config import SiteAuthConfig

    p = tmp_path / "x-auth.toml"
    p.write_text(
        '[oauth]\n'
        'issuer = "https://x.example.com/"\n'
        'jwks_uri = "https://x.example.com/jwks"\n'
        'audience = "my-resource"\n'
        'scopes = ["openid", "profile"]\n'
        'required_scopes = ["openid"]\n'
    )
    cfg = SiteAuthConfig.from_path(p)
    assert cfg.issuer == "https://x.example.com/"
    assert cfg.audience == "my-resource"
    assert cfg.scopes == ["openid", "profile"]


def test_load_with_optional_endpoints(tmp_path):
    from rucio_mcp.auth.site_config import SiteAuthConfig

    p = tmp_path / "full-auth.toml"
    p.write_text(
        '[oauth]\n'
        'issuer = "https://iam.example.com/"\n'
        'jwks_uri = "https://iam.example.com/jwk"\n'
        'audience = "rucio"\n'
        'scopes = ["openid"]\n'
        'required_scopes = ["openid"]\n'
        'authorization_endpoint = "https://iam.example.com/authorize"\n'
        'token_endpoint = "https://iam.example.com/token"\n'
        'registration_endpoint = "https://iam.example.com/register"\n'
    )
    cfg = SiteAuthConfig.from_path(p)
    assert cfg.authorization_endpoint == "https://iam.example.com/authorize"
    assert cfg.token_endpoint == "https://iam.example.com/token"
    assert cfg.registration_endpoint == "https://iam.example.com/register"


def test_missing_required_field_errors(tmp_path):
    from rucio_mcp.auth.site_config import SiteAuthConfig

    p = tmp_path / "bad.toml"
    p.write_text('[oauth]\nissuer = "https://x"\n')
    with pytest.raises(ValueError, match="missing required oauth keys"):
        SiteAuthConfig.from_path(p)


def test_missing_oauth_section_errors(tmp_path):
    from rucio_mcp.auth.site_config import SiteAuthConfig

    p = tmp_path / "nosection.toml"
    p.write_text('[other]\nfoo = "bar"\n')
    with pytest.raises(ValueError, match="missing required oauth keys"):
        SiteAuthConfig.from_path(p)


def test_unknown_site_errors():
    from rucio_mcp.auth.site_config import SiteAuthConfig

    with pytest.raises(ValueError, match="No auth config for site"):
        SiteAuthConfig.from_preset("nonexistent_site_xyz")


def test_preset_without_auth_resource_errors():
    """Preset that exists but has no auth_resource raises a clear error."""
    from rucio_mcp.auth.site_config import SiteAuthConfig
    from rucio_mcp.presets import PRESETS, Preset

    fake_preset = Preset(
        name="noauth",
        description="No auth resource",
        config_resource="atlas.cfg",
        post_init_hint="",
        auth_resource=None,
    )
    original = PRESETS.copy()
    PRESETS["noauth"] = fake_preset
    try:
        with pytest.raises(ValueError, match="No auth config for site"):
            SiteAuthConfig.from_preset("noauth")
    finally:
        PRESETS.clear()
        PRESETS.update(original)
