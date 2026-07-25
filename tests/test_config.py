"""Tests for configuration and settings."""

import pytest

from minilake.config import settings


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
