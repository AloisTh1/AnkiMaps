"""
Download the latest AnkiMaps release from GitHub and upload it to AnkiWeb.

First-time setup:
    uv pip install -e ".[publish]"
    playwright install chromium

Usage:
    python publish_ankiweb.py                  # fetch latest release, upload
    python publish_ankiweb.py --version 2.3.1  # fetch specific version
    python publish_ankiweb.py --local dist/AnkiMaps_2.3.1.ankiaddon
    python publish_ankiweb.py --login          # force fresh browser login
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

PYPROJECT_FILENAME = "pyproject.toml"
STATE_DIR = ".playwright-state"
STATE_FILE = os.path.join(STATE_DIR, "ankiweb_state.json")
ANKIWEB_ADDONS_URL = "https://ankiweb.net/shared/addons"
ANKIWEB_LOGIN_URL = "https://ankiweb.net/account/login"
REPO = "AloisTh1/AnkiMaps"


def get_version() -> str:
    version_pattern = re.compile(r'^version\s*=\s*["\']([^"\']+)["\']\s*$')
    in_project_section = False

    with open(PYPROJECT_FILENAME, "r", encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("[") and stripped.endswith("]"):
                in_project_section = stripped == "[project]"
                continue

            if not in_project_section:
                continue

            if match := version_pattern.match(stripped):
                return match.group(1).strip()

    raise RuntimeError("Could not read [project].version from pyproject.toml.")


def get_ankiweb_addon_id() -> str:
    addon_id_pattern = re.compile(r'^addon_id\s*=\s*["\']([^"\']+)["\']\s*$')
    in_ankiweb_section = False

    with open(PYPROJECT_FILENAME, "r", encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("[") and stripped.endswith("]"):
                in_ankiweb_section = stripped == "[tool.ankiweb]"
                continue

            if not in_ankiweb_section:
                continue

            if match := addon_id_pattern.match(stripped):
                return match.group(1).strip()

    raise RuntimeError("Could not read [tool.ankiweb].addon_id from pyproject.toml.")


def download_artifact(version: str) -> str:
    if not shutil.which("gh"):
        print("ERROR: 'gh' CLI not found. Install it from https://cli.github.com/")
        sys.exit(1)

    tag = f"v{version}"
    tmpdir = tempfile.mkdtemp(prefix="ankimaps_release_")

    print(f"Downloading release {tag} from {REPO}...")
    result = subprocess.run(
        ["gh", "release", "download", tag, "--repo", REPO, "--pattern", "*.ankiaddon", "--dir", tmpdir],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to download release {tag}.")
        print(result.stderr.strip())
        print("\nHint: use --version to specify a different version, or --local to use a local file.")
        shutil.rmtree(tmpdir, ignore_errors=True)
        sys.exit(1)

    files = glob.glob(os.path.join(tmpdir, "*.ankiaddon"))
    if len(files) != 1:
        print(f"ERROR: Expected 1 .ankiaddon file, found {len(files)} in release {tag}.")
        shutil.rmtree(tmpdir, ignore_errors=True)
        sys.exit(1)

    addon_path = files[0]
    size_kb = os.path.getsize(addon_path) / 1024
    print(f"Downloaded: {os.path.basename(addon_path)} ({size_kb:.1f} KB)")
    return addon_path


def ensure_logged_in(page, force_login: bool) -> None:
    if force_login and os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        print("Cleared saved login state.")

    page.goto(ANKIWEB_ADDONS_URL, wait_until="networkidle")

    if "/account/login" in page.url:
        print("\nNot logged in to AnkiWeb.")
        print("A browser window will open — please log in, then press Enter here.")
        input("Press Enter to open the browser...")

        # Re-launch in headed mode for interactive login
        return None  # Signal to caller that headed login is needed

    print("Logged in to AnkiWeb.")
    return True


def upload_to_ankiweb(addon_path: str, addon_id: str, *, force_login: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright is not installed.")
        print('Install it with: uv pip install -e ".[publish]" && playwright install chromium')
        sys.exit(1)

    os.makedirs(STATE_DIR, exist_ok=True)
    storage_state = STATE_FILE if os.path.exists(STATE_FILE) else None

    if force_login:
        storage_state = None
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            print("Cleared saved login state.")

    with sync_playwright() as p:
        # First try headless with saved state
        if not force_login and storage_state:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=storage_state)
            page = context.new_page()
            page.goto(ANKIWEB_ADDONS_URL, wait_until="networkidle")

            if "/account/login" not in page.url:
                print("Logged in to AnkiWeb (saved session).")
                _do_upload(page, context, addon_path, addon_id)
                context.close()
                browser.close()
                return

            print("Saved session expired.")
            context.close()
            browser.close()

        # Headed mode for interactive login
        print("\nOpening browser for AnkiWeb login...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(ANKIWEB_LOGIN_URL, wait_until="networkidle")

        print("Please log in to AnkiWeb in the browser window.")
        input("Press Enter here once you are logged in...")

        # Verify login succeeded
        page.goto(ANKIWEB_ADDONS_URL, wait_until="networkidle")
        if "/account/login" in page.url:
            print("ERROR: Still not logged in. Please try again.")
            context.close()
            browser.close()
            sys.exit(1)

        # Save session for next time
        context.storage_state(path=STATE_FILE)
        print(f"Login state saved to {STATE_FILE}")

        _do_upload(page, context, addon_path, addon_id)
        context.close()
        browser.close()


def _do_upload(page, context, addon_path: str, addon_id: str) -> None:
    upload_url = f"https://ankiweb.net/shared/upload?id={addon_id}"
    print(f"\nNavigating to upload page: {upload_url}")
    page.goto(upload_url, wait_until="networkidle")

    # Wait for the page content to load (SvelteKit SPA)
    page.wait_for_timeout(2000)

    # Look for a file input element
    file_input = page.query_selector('input[type="file"]')
    if not file_input:
        # Try waiting a bit longer for SPA rendering
        page.wait_for_selector('input[type="file"]', timeout=10000)
        file_input = page.query_selector('input[type="file"]')

    if not file_input:
        _save_debug_screenshot(page)
        print("ERROR: Could not find file upload input on the page.")
        print("A debug screenshot has been saved to publish_debug.png")
        print(f"Current URL: {page.url}")
        sys.exit(1)

    print(f"Uploading {os.path.basename(addon_path)}...")
    file_input.set_input_files(addon_path)

    # Look for a submit/upload button
    submit_button = page.get_by_role(
        "button", name=re.compile(r"upload|submit|save|update", re.IGNORECASE)
    ).first

    if not submit_button:
        _save_debug_screenshot(page)
        print("ERROR: Could not find submit button on the page.")
        print("A debug screenshot has been saved to publish_debug.png")
        sys.exit(1)

    print("Submitting upload...")
    submit_button.click()

    # Wait for navigation or success indicator
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # Save state after successful operation
    context.storage_state(path=STATE_FILE)

    _save_debug_screenshot(page)
    print(f"\nUpload complete. Current page: {page.url}")
    print(f"Check your addon at: https://ankiweb.net/shared/info/{addon_id}")
    print("A screenshot of the result page has been saved to publish_debug.png")


def _save_debug_screenshot(page) -> None:
    try:
        page.screenshot(path="publish_debug.png", full_page=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Upload AnkiMaps .ankiaddon to AnkiWeb.")
    parser.add_argument(
        "--version", help="Version to download (default: current version from pyproject.toml)"
    )
    parser.add_argument("--local", help="Path to a local .ankiaddon file (skip GitHub download)")
    parser.add_argument(
        "--login", action="store_true", help="Force fresh browser login (clear saved session)"
    )
    args = parser.parse_args()

    addon_id = get_ankiweb_addon_id()
    print(f"AnkiWeb addon ID: {addon_id}")

    # Resolve the .ankiaddon file
    if args.local:
        addon_path = args.local
        if not os.path.isfile(addon_path):
            print(f"ERROR: File not found: {addon_path}")
            sys.exit(1)
        size_kb = os.path.getsize(addon_path) / 1024
        print(f"Using local file: {addon_path} ({size_kb:.1f} KB)")
        tmpdir = None
    else:
        version = args.version or get_version()
        print(f"Target version: {version}")
        addon_path = download_artifact(version)
        tmpdir = os.path.dirname(addon_path)

    try:
        upload_to_ankiweb(addon_path, addon_id, force_login=args.login)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
