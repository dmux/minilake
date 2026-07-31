"""Tests for configuration and settings."""

import stat
from pathlib import Path

import pytest

from minilake.config import ensure_writable_dir, settings


@pytest.mark.smoke
def test_settings_loaded():
    """Test: Settings are loaded from environment or defaults."""
    assert settings is not None
    assert hasattr(settings, "data_dir")
    assert hasattr(settings, "host")
    assert hasattr(settings, "port")
    print("✓ Settings loaded")


@pytest.mark.smoke
def test_data_dir_is_valid():
    """Test: Data directory setting is valid."""
    assert settings.data_dir is not None
    # Should be a path or string
    data_dir_str = str(settings.data_dir)
    assert len(data_dir_str) > 0
    print(f"✓ Data dir: {data_dir_str}")


@pytest.mark.smoke
def test_host_and_port():
    """Test: Host and port settings."""
    assert settings.host in ["127.0.0.1", "localhost", "0.0.0.0"]
    assert isinstance(settings.port, int)
    assert settings.port > 0
    print(f"✓ Server: {settings.host}:{settings.port}")


@pytest.mark.crud
def test_ensure_writable_dir_opens_up_intermediate_dirs(monkeypatch, tmp_path: Path):
    """Every level from data_dir down to the leaf ends up world-writable.

    Sibling containers run as their own UID (Spark uses 185), so a root-owned
    0755 directory anywhere in the chain makes their writes fail.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    leaf = tmp_path / "delta" / "cat" / "sch" / "tbl"

    ensure_writable_dir(leaf)

    for path in (tmp_path, tmp_path / "delta", tmp_path / "delta" / "cat", leaf):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o777 == 0o777, f"{path} is {oct(mode)}, not world-writable"

    print("✓ ensure_writable_dir chmods the whole chain up to data_dir")


@pytest.mark.crud
def test_ensure_writable_dir_stops_at_data_dir(monkeypatch, tmp_path: Path):
    """Directories above data_dir are left alone."""
    root = tmp_path / "outer"
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    root.chmod(0o755)
    monkeypatch.setattr(settings, "data_dir", data_dir)

    ensure_writable_dir(data_dir / "delta")

    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    print("✓ ensure_writable_dir does not walk above data_dir")
