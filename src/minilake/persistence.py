"""Optional JSON snapshot persistence for minilake state.

Modules expose get_state()/restore_state()/reset() functions which are
orchestrated here: state is snapshotted to a version-stamped JSON envelope
on shutdown (if MINILAKE_PERSIST=1) and reloaded on startup.
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
SUPPORTED_MIN_FORMAT_VERSION = 1
SUPPORTED_MAX_FORMAT_VERSION = 1


class StateEnvelope:
    """Version-stamped state snapshot envelope."""

    def __init__(self, modules_state: dict[str, Any]):
        self.format_version = FORMAT_VERSION
        self.modules = modules_state

    def to_dict(self) -> dict:
        return {
            "format_version": self.format_version,
            "modules": self.modules,
        }

    @staticmethod
    def from_dict(data: dict) -> "StateEnvelope":
        """Load from dict, raising if version is incompatible."""
        version = data.get("format_version", 1)
        if version < SUPPORTED_MIN_FORMAT_VERSION or version > SUPPORTED_MAX_FORMAT_VERSION:
            raise ValueError(
                f"Snapshot format version {version} not supported "
                f"(this binary supports {SUPPORTED_MIN_FORMAT_VERSION}-{SUPPORTED_MAX_FORMAT_VERSION})"
            )
        return StateEnvelope(data.get("modules", {}))


async def save_state(
    snapshot_path: Path,
    get_state_funcs: dict[str, Callable[[], dict[str, Any]]],
) -> None:
    """Save state from all modules to a snapshot file."""
    modules_state = {}
    for name, get_state_func in get_state_funcs.items():
        try:
            modules_state[name] = get_state_func()
        except Exception as e:
            logger.warning(f"Failed to get state from {name}: {e}")

    envelope = StateEnvelope(modules_state)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(snapshot_path, "w") as f:
            json.dump(envelope.to_dict(), f, indent=2)
        logger.info(f"Saved state snapshot to {snapshot_path}")
    except Exception as e:
        logger.error(f"Failed to save state snapshot: {e}")


async def load_state(
    snapshot_path: Path,
    restore_state_funcs: dict[str, Callable[[dict[str, Any]], None]],
) -> None:
    """Load state from snapshot and restore to all modules."""
    if not snapshot_path.exists():
        logger.debug(f"No snapshot file at {snapshot_path}")
        return

    try:
        with open(snapshot_path) as f:
            data = json.load(f)
        envelope = StateEnvelope.from_dict(data)
    except Exception as e:
        logger.error(f"Failed to load state snapshot: {e}")
        return

    for name, restore_state_func in restore_state_funcs.items():
        module_state = envelope.modules.get(name)
        if module_state is None:
            continue
        try:
            restore_state_func(module_state)
            logger.info(f"Restored state for {name}")
        except Exception as e:
            logger.warning(f"Failed to restore state for {name}: {e}")
