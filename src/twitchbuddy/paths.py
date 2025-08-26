from __future__ import annotations

import os
import platform
from pathlib import Path


def default_data_dir(app_name: str = "TwitchBuddy") -> Path:
    """Return a writable per-platform data directory for the application.

    Priority:
      - Windows: %LOCALAPPDATA% (fallback %APPDATA%, then %PROGRAMDATA%)
      - macOS: ~/Library/Application Support/{app_name}
      - Linux/Unix: $XDG_DATA_HOME or ~/.local/share/{app_name}
      - Fallback: current working directory
    The directory is created if it doesn't exist.
    """
    # Allow an explicit override of the data directory via env var
    env_override = os.environ.get("TWITCHBUDDY_DATA_DIR")
    if env_override:
        p = Path(env_override).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            # fall through to platform-specific defaults if creation fails
            pass

    system = platform.system()
    if system == "Windows":
        # prefer local app data for per-user, machine-local writable folder
        local = os.environ.get("LOCALAPPDATA")
        roaming = os.environ.get("APPDATA")
        programdata = os.environ.get("PROGRAMDATA")
        for candidate in (local, roaming, programdata):
            if candidate:
                p = Path(candidate) / app_name
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    return p
                except Exception:
                    continue
    elif system == "Darwin":
        home = Path.home()
        p = home / "Library" / "Application Support" / app_name
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    else:
        # Linux / other Unix-like
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            p = Path(xdg) / app_name
        else:
            p = Path.home() / ".local" / "share" / app_name
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass

    # Final fallback: cwd
    p = Path.cwd() / app_name
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def default_db_path(
    filename: str = "TwitchBuddy.db", app_name: str = "TwitchBuddy"
) -> Path:
    """Return a full path to a database filename inside the default data dir."""
    # Allow overriding the full DB path directly via env var
    db_override = os.environ.get("TWITCHBUDDY_DB_PATH")
    if db_override:
        return Path(db_override).expanduser()

    dirpath = default_data_dir(app_name)
    return dirpath / filename
