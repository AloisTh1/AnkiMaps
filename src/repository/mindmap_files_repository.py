import json
import os
import zipfile
from typing import Optional

from ..common.io import (
    export_mindmap_file,
    get_mindmap_backup_count,
    get_mindmap_file_metadata,
    get_mindmap_file_names,
    import_mindmap_file,
    resolve_available_mindmap_name,
)


class MindmapFilesRepository:
    BUNDLE_MAP_FILENAME = "mindmap.json"
    BUNDLE_DECK_FILENAME = "notes.apkg"

    def get_mindmap_names(self) -> list[str]:
        mindmap_files = get_mindmap_file_names()
        return sorted([f[:-3] for f in mindmap_files if f.endswith(".db")])

    def get_mindmap_file_metadata(self, mindmap_name: str) -> dict:
        return get_mindmap_file_metadata(mindmap_name)

    def get_mindmap_backup_count(self, mindmap_name: str) -> Optional[int]:
        return get_mindmap_backup_count(mindmap_name)

    def export_mindmap(self, mindmap_name: str, destination_file_path: str) -> None:
        export_mindmap_file(mindmap_name, destination_file_path)

    def import_mindmap(self, source_file_path: str) -> tuple[str, bool]:
        return import_mindmap_file(source_file_path)

    def resolve_available_mindmap_name(self, preferred_name: str) -> tuple[str, bool]:
        return resolve_available_mindmap_name(preferred_name)

    def write_bundle(self, destination_file_path: str, payload: dict) -> None:
        with open(destination_file_path, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, indent=2)

    def read_bundle(self, source_file_path: str) -> dict:
        with open(source_file_path, "r", encoding="utf-8") as input_file:
            data = json.load(input_file)
        if not isinstance(data, dict):
            raise ValueError("Invalid bundle format: expected a JSON object.")
        return data

    def write_bundle_archive(self, destination_file_path: str, payload: dict, apkg_file_path: str) -> None:
        if not apkg_file_path or not os.path.isfile(apkg_file_path):
            raise FileNotFoundError("Could not find generated .apkg file for bundle export.")

        with zipfile.ZipFile(destination_file_path, "w", zipfile.ZIP_DEFLATED) as bundle_zip:
            bundle_zip.writestr(self.BUNDLE_MAP_FILENAME, json.dumps(payload, indent=2))
            bundle_zip.write(apkg_file_path, arcname=self.BUNDLE_DECK_FILENAME)

    def read_bundle_archive(
        self, source_file_path: str, extract_directory: str
    ) -> tuple[dict, Optional[str]]:
        with zipfile.ZipFile(source_file_path, "r") as bundle_zip:
            members = set(bundle_zip.namelist())
            if self.BUNDLE_MAP_FILENAME not in members:
                raise ValueError("Bundle archive does not contain mindmap.json.")

            bundle_zip.extract(self.BUNDLE_MAP_FILENAME, path=extract_directory)
            map_file_path = os.path.join(extract_directory, self.BUNDLE_MAP_FILENAME)

            with open(map_file_path, "r", encoding="utf-8") as map_file:
                payload = json.load(map_file)

            apkg_file_path: Optional[str] = None
            if self.BUNDLE_DECK_FILENAME in members:
                bundle_zip.extract(self.BUNDLE_DECK_FILENAME, path=extract_directory)
                apkg_file_path = os.path.join(extract_directory, self.BUNDLE_DECK_FILENAME)

        if not isinstance(payload, dict):
            raise ValueError("Invalid bundle format: expected a JSON object.")
        return payload, apkg_file_path
