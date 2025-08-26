"""TwitchBuddy package.

Load a local .env file if present (development convenience). The loader is
optional and will be a no-op if `python-dotenv` is not installed.
"""

from typing import List

__all__: List[str] = ["greet"]

try:
    # python-dotenv is an optional dev convenience.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # if python-dotenv isn't installed, that's fine — env vars may come from
    # the OS or CI environment.
    pass

from .core import greet
