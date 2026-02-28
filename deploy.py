import argparse
import json
import os
import platform
import re
import shutil

PYPROJECT_FILENAME = "pyproject.toml"


parser = argparse.ArgumentParser(description="Deploy or remove the AnkiMaps addon for local development.")
parser.add_argument(
    "-d", "--delete", action="store_true", help="Remove (uninstall) the addon instead of deploying it."
)
args = parser.parse_args()


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


VERSION = get_version()


user_home = os.path.expanduser("~")

if platform.system() == "Windows":
    local_path = os.path.join(user_home, "AppData", "Roaming", "Anki2", "addons21", "AnkiMaps")
else:
    local_path = os.path.join(user_home, ".local", "share", "Anki2", "addons21", "AnkiMaps")

if args.delete:
    if os.path.exists(local_path):
        print(f"Removing addon from {local_path}...")
        try:
            shutil.rmtree(local_path)
            print("Addon successfully removed.")
        except OSError as e:
            print(f"Error removing addon: {e}")
    else:
        print(f"Addon not found at {local_path}. Nothing to remove.")
else:
    source_dir = "src"
    files_to_copy = ["__init__.py", "README.md", "LICENSE.txt"]

    os.makedirs(local_path, exist_ok=True)

    target_src_path = os.path.join(local_path, "src")
    if os.path.exists(target_src_path):
        shutil.rmtree(target_src_path)
    shutil.copytree(source_dir, target_src_path)

    for file in files_to_copy:
        shutil.copy(file, local_path)

    manifest = {
        "name": "AnkiMaps",
        "author": "Aloïs Thibert",
        "authorUrl": "https://github.com/AloisTh1/",
        "package": "AnkiMaps",
        "version": VERSION,
        "isDesktopOnly": True,
    }
    with open(os.path.join(local_path, "manifest.json"), "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, indent=4)

    print(f"Deployed files to {local_path}")
    print(f"Wrote manifest.json with version: {VERSION}")
