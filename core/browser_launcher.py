"""
Shared browser launcher - Chromium 126 ONLY.

The tool always runs its own Chromium 126 build from
browsers/chromium-126/ inside the tool folder. The device's
installed Chrome is never used, and there is no fallback:
if the 126 build is missing or is not version 126, launching
stops with an error.

Used by all browser-based modes.
"""
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent.parent
_CHROMIUM126_DIR = _TOOL_ROOT / "browsers" / "chromium-126"
_CHROMIUM126_URL = (
    "https://storage.googleapis.com/chrome-for-testing-public/"
    "126.0.6478.182/win64/chrome-win64.zip"
)


def _find_chromium126():
    """Return the tool's Chromium 126 chrome.exe path, or None."""
    for _candidate in (
        _CHROMIUM126_DIR / "chrome.exe",
        _CHROMIUM126_DIR / "chrome-win64" / "chrome.exe",
    ):
        if _candidate.exists():
            return str(_candidate)
    return None


def get_browser_choice():
    """No choice anymore: the tool always uses Chromium 126."""
    print("\n" + "=" * 50)
    print("Browser: Chromium 126 (tool build)")
    print("=" * 50)
    return "chromium126"


def launch_browser(p, browser_type="chromium", headless=False, extra_args=None):
    """
    Launch the tool's own Chromium 126 build.
    Returns (browser, is_cloak) tuple - is_cloak is always False.
    Raises RuntimeError if the 126 build is missing or wrong version.
    There is NO fallback to any other browser.
    """
    _exe = _find_chromium126()
    if not _exe:
        raise RuntimeError(
            "Chromium 126 build not found. Download it from "
            + _CHROMIUM126_URL
            + " and extract it into "
            + str(_CHROMIUM126_DIR)
            + " so that chrome.exe is inside that folder. "
            "The tool runs Chromium 126 only - no other browser is used."
        )
    args = ["--disable-blink-features=AutomationControlled"]
    if extra_args:
        args = args + list(extra_args)
    browser = p.chromium.launch(
        executable_path=_exe, headless=headless, args=args
    )
    _version = str(browser.version)
    if not _version.startswith("126."):
        try:
            browser.close()
        except Exception:
            pass
        raise RuntimeError(
            f"Wrong browser version: {_version}. "
            "The tool runs Chromium 126 only - put the 126 build in "
            + str(_CHROMIUM126_DIR)
        )
    print(f"[Browser] Chromium {_version} launched")
    return browser, False
