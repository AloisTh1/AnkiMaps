import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from shutil import copy2

from ..common.constants import ANKIMAPS_CONSTANTS
from ..common.io import get_anki_addon_path

SKIP_TOP_LEVEL = {ANKIMAPS_CONSTANTS.USER_FILES_DIRECTORY_NAME.value}
SKIP_ANYWHERE = {"__pycache__"}


@dataclass
class UpgradeResult:
    copied_files: int
    package_version: str
    current_version: str


class AddonUpgradeRepository:
    def _resolve_archive_root(self, extract_dir: str) -> str:
        direct_manifest = os.path.join(extract_dir, "manifest.json")
        if os.path.isfile(direct_manifest):
            return extract_dir

        children = [
            os.path.join(extract_dir, entry)
            for entry in os.listdir(extract_dir)
            if os.path.isdir(os.path.join(extract_dir, entry))
        ]
        if len(children) == 1 and os.path.isfile(os.path.join(children[0], "manifest.json")):
            return children[0]

        return extract_dir

    def _read_manifest(self, root_path: str) -> dict:
        manifest_path = os.path.join(root_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            return {}

        try:
            with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                return json.load(manifest_file)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid manifest.json in package.") from exc

    def _extract_version(self, root_path: str) -> str:
        manifest = self._read_manifest(root_path)
        manifest_version = manifest.get("version")
        if manifest_version:
            return str(manifest_version).strip()

        return ""

    def _validate_package_identity(self, root_path: str) -> None:
        manifest = self._read_manifest(root_path)
        package_name = manifest.get("package")
        if package_name and package_name != ANKIMAPS_CONSTANTS.ADD_ON_NAME.value:
            raise ValueError(
                f"Package mismatch: expected '{ANKIMAPS_CONSTANTS.ADD_ON_NAME.value}', got '{package_name}'."
            )

    def _parse_numeric_version(self, version: str):
        cleaned = version.strip()
        if re.fullmatch(r"\d+(\.\d+)*", cleaned):
            return [int(part) for part in cleaned.split(".")]
        return None

    def _is_older_version(self, package_version: str, current_version: str) -> bool:
        package_numeric = self._parse_numeric_version(package_version)
        current_numeric = self._parse_numeric_version(current_version)

        if package_numeric is not None and current_numeric is not None:
            max_len = max(len(package_numeric), len(current_numeric))
            package_tuple = tuple(package_numeric + [0] * (max_len - len(package_numeric)))
            current_tuple = tuple(current_numeric + [0] * (max_len - len(current_numeric)))
            return package_tuple < current_tuple

        return package_version.strip() < current_version.strip()

    def get_current_version(self) -> str:
        addon_path = get_anki_addon_path()
        if not addon_path:
            return "unknown"

        current_version = self._extract_version(addon_path)
        return current_version or "unknown"

    def apply_package(self, archive_path: str) -> UpgradeResult:
        addon_path = get_anki_addon_path()
        if not addon_path:
            raise RuntimeError("Could not determine addon path.")

        if not os.path.isfile(archive_path):
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        copied_files = 0
        current_version = self.get_current_version()

        with tempfile.TemporaryDirectory(prefix="ankimaps_upgrade_") as temp_dir:
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(temp_dir)

            archive_root = self._resolve_archive_root(temp_dir)
            self._validate_package_identity(archive_root)

            package_version = self._extract_version(archive_root)
            if not package_version:
                raise ValueError("Upgrade package has no version metadata (manifest version).")

            if current_version != "unknown" and self._is_older_version(package_version, current_version):
                raise ValueError(
                    f"Refusing downgrade: package version {package_version} is older than installed version {current_version}."
                )

            for root, dirs, files in os.walk(archive_root):
                rel_root = os.path.relpath(root, archive_root)

                filtered_dirs = []
                for directory in dirs:
                    if directory in SKIP_ANYWHERE:
                        continue
                    if rel_root == "." and directory in SKIP_TOP_LEVEL:
                        continue
                    filtered_dirs.append(directory)
                dirs[:] = filtered_dirs

                target_root = addon_path if rel_root == "." else os.path.join(addon_path, rel_root)
                os.makedirs(target_root, exist_ok=True)

                for file_name in files:
                    if file_name.endswith(".pyc"):
                        continue

                    source_file = os.path.join(root, file_name)
                    target_file = os.path.join(target_root, file_name)
                    copy2(source_file, target_file)
                    copied_files += 1

        return UpgradeResult(
            copied_files=copied_files,
            package_version=package_version,
            current_version=current_version,
        )
