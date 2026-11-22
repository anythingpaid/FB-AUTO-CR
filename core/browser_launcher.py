"""
Shared browser launcher - Chromium 126 ONLY.

The tool always runs its own Chromium 126 build from
browsers/chromium-126/ inside the tool folder. The device's
installed Chrome is never used, and there is no fallback:
if the 126 build is missing it is downloaded automatically,
and if it is not version 126, launching stops with an error.

Used by all browser-based modes.
"""
import urllib.request
import zipfile
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


def _ensure_chromium126():
    """Return the Chromium 126 chrome.exe path, downloading and
    extracting the official build automatically on first run.
    Raises RuntimeError if the download or extract fails.
    There is NO fallback to any other browser."""
    _exe = _find_chromium126()
    if _exe:
        return _exe
    _CHROMIUM126_DIR.mkdir(parents=True, exist_ok=True)
    _zip_path = _CHROMIUM126_DIR / "chrome-win64.zip"
    print("[Browser] Chromium 126 not found - downloading it now (one time, ~180 MB)...")
    try:
        urllib.request.urlretrieve(_CHROMIUM126_URL, _zip_path)
        print("[Browser] Download complete - extracting...")
        with zipfile.ZipFile(_zip_path) as _zip:
            _zip.extractall(_CHROMIUM126_DIR)
    except Exception as e:
        raise RuntimeError(
            f"Chromium 126 automatic download failed: {e}. "
            "Check your internet connection and run again. "
            "The tool runs Chromium 126 only - no other browser is used."
        )
    finally:
        try:
            _zip_path.unlink()
        except Exception:
            pass
    _exe = _find_chromium126()
    if not _exe:
        raise RuntimeError(
            "Chromium 126 was downloaded but chrome.exe was not found after extracting. "
            "The tool runs Chromium 126 only - no other browser is used."
        )
    print("[Browser] Chromium 126 ready")
    return _exe


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
    _exe = _ensure_chromium126()
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
