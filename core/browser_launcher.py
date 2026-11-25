"""
Shared browser launcher - 4 browsers with rotation support.

Browsers:
  chromium126 : the tool's own Chromium 126 build in
                browsers/chromium-126/ (auto-downloaded).
  clearcote   : Clearcote anti-fingerprint Chromium (pip SDK,
                auto-downloads its own build, seeded persona).
  fingerprint : fingerprint-chromium (adryfish) in
                browsers/fingerprint-chromium/ (auto-downloaded,
                --fingerprint seed per launch).
  apostate    : Apostate anti-detect Chromium (pip SDK,
                auto-downloads its own build, seeded persona).
  rotation    : cycle through all 4, one browser per ID.

The device's installed Chrome is never used. There is no
fallback: if a chosen browser cannot start, launching stops
with an error.

Used by all browser-based modes.
"""
import random
import urllib.request
import zipfile
from pathlib import Path

_TOOL_ROOT = Path(__file__).resolve().parent.parent
_CHROMIUM126_DIR = _TOOL_ROOT / "browsers" / "chromium-126"
_CHROMIUM126_URL = (
    "https://storage.googleapis.com/chrome-for-testing-public/"
    "126.0.6478.182/win64/chrome-win64.zip"
)
_FP_DIR = _TOOL_ROOT / "browsers" / "fingerprint-chromium"
_FP_URL = (
    "https://github.com/adryfish/fingerprint-chromium/releases/"
    "download/150.0.7871.186/"
    "ungoogled-chromium_150.0.7871.186-1.1_windows_x64.zip"
)

ROTATION_BROWSERS = ["chromium126", "clearcote", "fingerprint", "apostate"]


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
    Raises RuntimeError if the download or extract fails."""
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
            "Check your internet connection and run again."
        )
    finally:
        try:
            _zip_path.unlink()
        except Exception:
            pass
    _exe = _find_chromium126()
    if not _exe:
        raise RuntimeError(
            "Chromium 126 was downloaded but chrome.exe was not found after extracting."
        )
    print("[Browser] Chromium 126 ready")
    return _exe


_FP_EXE_CACHE = [None]


def _find_fingerprint_chromium():
    """Return the fingerprint-chromium chrome.exe path, or None.
    The found path is cached for the process: the extracted tree
    is large, and walking it on every launch made the browser
    slow to open."""
    if _FP_EXE_CACHE[0]:
        return _FP_EXE_CACHE[0]
    if not _FP_DIR.exists():
        return None
    _candidate = next(_FP_DIR.rglob("chrome.exe"), None)
    if _candidate is None:
        return None
    _FP_EXE_CACHE[0] = str(_candidate)
    return _FP_EXE_CACHE[0]


def _ensure_fingerprint_chromium():
    """Return the fingerprint-chromium chrome.exe path, downloading
    and extracting the official build automatically on first run.
    Raises RuntimeError if the download or extract fails."""
    _exe = _find_fingerprint_chromium()
    if _exe:
        return _exe
    _FP_DIR.mkdir(parents=True, exist_ok=True)
    _zip_path = _FP_DIR / "fingerprint-chromium.zip"
    print("[Browser] fingerprint-chromium not found - downloading it now (one time, ~180 MB)...")
    try:
        urllib.request.urlretrieve(_FP_URL, _zip_path)
        print("[Browser] Download complete - extracting...")
        with zipfile.ZipFile(_zip_path) as _zip:
            _zip.extractall(_FP_DIR)
    except Exception as e:
        raise RuntimeError(
            f"fingerprint-chromium automatic download failed: {e}. "
            "Check your internet connection and run again."
        )
    finally:
        try:
            _zip_path.unlink()
        except Exception:
            pass
    _exe = _find_fingerprint_chromium()
    if not _exe:
        raise RuntimeError(
            "fingerprint-chromium was downloaded but chrome.exe was not found after extracting."
        )
    print("[Browser] fingerprint-chromium ready")
    return _exe


def _launch_chromium126(p, headless, extra_args):
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
            "Put the Chromium 126 build in " + str(_CHROMIUM126_DIR)
        )
    print(f"[Browser] Chromium {_version} launched")
    return browser, False


def _launch_clearcote(p, headless, extra_args):
    try:
        from clearcote import executable_path as _cc_executable_path
    except ImportError:
        raise RuntimeError(
            "Clearcote is not installed. Run: pip install clearcote"
        )
    _exe = _cc_executable_path()
    _seed = random.randint(1, 2**31 - 1)
    args = [f"--fingerprint={_seed}"]
    if extra_args:
        args = args + list(extra_args)
    browser = p.chromium.launch(
        executable_path=_exe, headless=headless, args=args
    )
    print(f"[Browser] Clearcote launched (seed {_seed})")
    return browser, True


def _launch_fingerprint(p, headless, extra_args):
    _exe = _ensure_fingerprint_chromium()
    _seed = random.randint(1, 2**31 - 1)
    args = [
        f"--fingerprint={_seed}",
        "--fingerprint-platform=windows",
        "--fingerprint-brand=Chrome",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-background-networking",
        "--disable-component-update",
        "--mute-audio",
    ]
    if extra_args:
        args = args + list(extra_args)
    browser = p.chromium.launch(
        executable_path=_exe, headless=headless, args=args
    )
    print(f"[Browser] fingerprint-chromium launched (seed {_seed})")
    return browser, True


def _find_apostate():
    """Return the Apostate chrome.exe path, or None."""
    import os

    _roots = []
    _local = os.environ.get("LOCALAPPDATA")
    if _local:
        _roots.append(Path(_local) / "apostate")
    _roots.append(Path.home() / ".cache" / "apostate")
    for _root in _roots:
        if _root.exists():
            for _candidate in sorted(_root.rglob("chrome.exe")):
                return str(_candidate)
    return None


def _ensure_apostate_manifest(exe):
    """Apostate's Windows build ships without the side-by-side assembly
    manifest its chrome.exe depends on, so Windows refuses to start it
    ("side-by-side configuration is incorrect"). Write the manifest
    next to chrome.exe when it is missing."""
    import re

    _exe_path = Path(exe)
    _version = _exe_path.parent.parent.parent.name
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", _version):
        return
    _manifest = _exe_path.parent / f"{_version}.manifest"
    if _manifest.exists():
        return
    _dlls = [
        "chrome.dll",
        "chrome_elf.dll",
        "d3dcompiler_47.dll",
        "libEGL.dll",
        "libGLESv2.dll",
        "vk_swiftshader.dll",
        "vulkan-1.dll",
        "mojo_core.dll",
    ]
    _files = "\n".join(
        f'  <file name="{_dll}"/>'
        for _dll in _dlls
        if (_exe_path.parent / _dll).exists()
    )
    _manifest.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" '
        'manifestVersion="1.0">\n'
        f'  <assemblyIdentity name="{_version}" version="{_version}" '
        'type="win32"/>\n'
        f"{_files}\n"
        "</assembly>\n",
        encoding="utf-8",
    )


def _ensure_apostate():
    """Return the Apostate chrome.exe path, downloading the build
    automatically on first run (python -m apostate install).
    Raises RuntimeError if the install fails."""
    _exe = _find_apostate()
    if _exe:
        _ensure_apostate_manifest(_exe)
        return _exe
    try:
        import apostate  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Apostate is not installed. Run: pip install apostate"
        )
    import subprocess
    import sys

    print("[Browser] Apostate not found - downloading it now (one time, ~180 MB)...")
    _result = subprocess.run(
        [sys.executable, "-m", "apostate", "install"],
        capture_output=True,
        text=True,
    )
    _exe = _find_apostate()
    if not _exe:
        raise RuntimeError(
            "Apostate automatic download failed. "
            "Check your internet connection and run again. "
            f"Installer said: {(_result.stderr or _result.stdout or '')[-300:]}"
        )
    _ensure_apostate_manifest(_exe)
    print("[Browser] Apostate ready")
    return _exe


def _launch_apostate(p, headless, extra_args):
    _exe = _ensure_apostate()
    _seed = random.randint(1, 2**31 - 1)
    args = [
        f"--fingerprint={_seed}",
        "--fingerprint-platform=windows",
    ]
    if extra_args:
        args = args + list(extra_args)
    browser = p.chromium.launch(
        executable_path=_exe, headless=headless, args=args
    )
    print(f"[Browser] Apostate launched (seed {_seed})")
    return browser, True


def get_browser_choice():
    """Ask which browser to use. Returns one of:
    chromium126 / clearcote / fingerprint / apostate / rotation."""
    print("\n" + "=" * 50)
    print("Browser Setup:")
    print("  1. Chromium 126")
    print("  2. Clearcote")
    print("  3. Fingerprint-Chromium")
    print("  4. Apostate")
    print("  5. Browser Rotation")
    print("=" * 50)
    try:
        _choice = input("Choose browser (1-5): ").strip()
    except Exception:
        _choice = "5"
    _map = {
        "1": "chromium126",
        "2": "clearcote",
        "3": "fingerprint",
        "4": "apostate",
        "5": "rotation",
    }
    _picked = _map.get(_choice, "rotation")
    print(f"[Browser] Selected: {_picked}")
    return _picked


def launch_browser(p, browser_type="chromium126", headless=False, extra_args=None):
    """
    Launch the chosen browser.
    Returns (browser, is_spoofed) - is_spoofed is True when the
    browser manages its own fingerprint (the caller must then
    use a plain context with no UA/viewport overrides).
    Raises RuntimeError if the browser cannot start. No fallback.
    """
    _bt = (browser_type or "chromium126").lower()
    if _bt in ("chromium126", "chromium"):
        return _launch_chromium126(p, headless, extra_args)
    if _bt == "clearcote":
        return _launch_clearcote(p, headless, extra_args)
    if _bt == "fingerprint":
        return _launch_fingerprint(p, headless, extra_args)
    if _bt == "apostate":
        return _launch_apostate(p, headless, extra_args)
    raise RuntimeError(f"Unknown browser type: {browser_type}")
