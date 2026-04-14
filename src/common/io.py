import os
import os.path
from datetime import datetime
from shutil import copy2, move, rmtree
from typing import Optional, Union

from aqt.utils import showWarning

from .constants import ANKIMAPS_CONSTANTS


def get_loaded_anki_addon_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_add_on_last_mindmap_file_path() -> Union[str, None]:
    # TODO : allow user to sort maps etc...
    if anki_addon_user_files_path := get_anki_addon_user_files_path():
        return os.path.join(
            anki_addon_user_files_path,
            "last_used_map",
        )


def get_latest_loaded_mindmap() -> Union[str, None]:
    if last_mindmap_file_path := get_add_on_last_mindmap_file_path():
        if os.path.isfile(last_mindmap_file_path):
            with open(last_mindmap_file_path, "r+") as last_mindmap_file:
                return last_mindmap_file.readline()


def check_if_mindmap_exists(mindmap_path: str):
    if mindmap_path:
        return os.path.isfile(mindmap_path)


def get_anki_addon_path() -> Union[str, None]:
    return get_loaded_anki_addon_path()


def get_anki_addon_user_files_path() -> Union[str, None]:
    if anki_addon_path := get_anki_addon_path():
        return os.path.join(anki_addon_path, ANKIMAPS_CONSTANTS.USER_FILES_DIRECTORY_NAME.value)


def get_mindmaps_storage_path() -> Union[str, None]:
    if anki_addon_user_files_path := get_anki_addon_user_files_path():
        return os.path.join(
            anki_addon_user_files_path,
            ANKIMAPS_CONSTANTS.MINDMAP_DIRECTORY_NAME.value,
        )


def get_add_on_db_path(mindmap_name: str) -> Union[str, None]:
    if mindmaps_files_paths := get_mindmaps_storage_path():
        return os.path.join(
            mindmaps_files_paths,
            f"{mindmap_name}.db",
        )


def get_mindmap_file_names() -> list[str]:
    if mindmaps_storage_path := get_mindmaps_storage_path():
        if os.path.isdir(mindmaps_storage_path):
            return os.listdir(mindmaps_storage_path)
    return []


def get_mindmap_file_metadata(mindmap_name: str) -> dict:
    """
    Returns filesystem metadata for a mindmap database file.
    """
    db_path = get_add_on_db_path(mindmap_name)
    if not db_path or not os.path.isfile(db_path):
        return {}

    try:
        stats = os.stat(db_path)
    except OSError:
        return {}

    return {
        "created_at": stats.st_ctime,
        "modified_at": stats.st_mtime,
        "size_bytes": stats.st_size,
    }


def get_mindmap_backup_count(mindmap_name: str) -> Optional[int]:
    """
    Returns how many backup files are currently stored for a given mindmap.
    """
    backup_dir = get_mindmap_backup_path(mindmap_name)
    if not backup_dir or not os.path.isdir(backup_dir):
        return 0

    try:
        return len([f for f in os.listdir(backup_dir) if f.startswith("backup_") and f.endswith(".db")])
    except OSError:
        return None


def initialize_user_directories() -> None:
    if mindmaps_storage_path := get_mindmaps_storage_path():
        os.makedirs(mindmaps_storage_path, exist_ok=True)
    if backups_storage_path := get_backups_storage_path():
        os.makedirs(backups_storage_path, exist_ok=True)
    migrate_legacy_user_files()


def migrate_legacy_user_files() -> None:
    current_user_files_path = get_anki_addon_user_files_path()
    current_mindmaps_path = get_mindmaps_storage_path()
    if not (current_user_files_path and current_mindmaps_path):
        return

    loaded_addon_path = get_loaded_anki_addon_path()
    addons_folder_path = os.path.dirname(loaded_addon_path)
    legacy_user_files_path = os.path.join(
        addons_folder_path,
        ANKIMAPS_CONSTANTS.ADD_ON_NAME.value,
        ANKIMAPS_CONSTANTS.USER_FILES_DIRECTORY_NAME.value,
    )

    if os.path.normcase(os.path.abspath(legacy_user_files_path)) == os.path.normcase(
        os.path.abspath(current_user_files_path)
    ):
        return
    if not os.path.isdir(legacy_user_files_path):
        return

    legacy_mindmaps_path = os.path.join(
        legacy_user_files_path,
        ANKIMAPS_CONSTANTS.MINDMAP_DIRECTORY_NAME.value,
    )
    if not os.path.isdir(legacy_mindmaps_path):
        return
    if any(name.endswith(".db") for name in os.listdir(current_mindmaps_path)):
        return
    if not any(name.endswith(".db") for name in os.listdir(legacy_mindmaps_path)):
        return

    copy_user_files(legacy_user_files_path, current_user_files_path)


def copy_user_files(source_root: str, target_root: str) -> None:
    for root, dirs, files in os.walk(source_root):
        rel_root = os.path.relpath(root, source_root)
        target_dir = target_root if rel_root == "." else os.path.join(target_root, rel_root)
        os.makedirs(target_dir, exist_ok=True)

        for file_name in files:
            source_file = os.path.join(root, file_name)
            target_file = os.path.join(target_dir, file_name)
            if not os.path.exists(target_file):
                copy2(source_file, target_file)


def get_backups_storage_path() -> Union[str, None]:
    """Returns the path to the main 'backups' directory."""
    if anki_addon_user_files_path := get_anki_addon_user_files_path():
        return os.path.join(
            anki_addon_user_files_path,
            ANKIMAPS_CONSTANTS.BACKUPS_DIRECTORY_NAME.value,
        )


def get_mindmap_backup_path(mindmap_name: str) -> Union[str, None]:
    """Returns the path to the backup directory for a specific mindmap."""
    if backups_storage_path := get_backups_storage_path():
        return os.path.join(backups_storage_path, mindmap_name)


def create_backup(mindmap_name: str, max_backups: int) -> bool:
    """
    Creates a timestamped backup of a mindmap's .db file and rotates old backups.

    :param mindmap_name: The name of the mindmap to back up.
    :param max_backups: The maximum number of backups to keep.
    :return: True if the backup was successful, False otherwise.
    """
    source_db_path = get_add_on_db_path(mindmap_name)
    if not (source_db_path and os.path.exists(source_db_path)):
        return False

    backup_dir = get_mindmap_backup_path(mindmap_name)
    if not backup_dir:
        return False

    try:
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"backup_{timestamp}.db"
        backup_filepath = os.path.join(backup_dir, backup_filename)
        copy2(source_db_path, backup_filepath)

        all_backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("backup_") and f.endswith(".db")]
        )

        if len(all_backups) > max_backups:
            backups_to_delete = all_backups[: len(all_backups) - max_backups]
            for old_backup in backups_to_delete:
                os.remove(os.path.join(backup_dir, old_backup))

        return True
    except (OSError, IOError):
        return False


def delete_mindmap_file(mindmap_name: str) -> bool:
    """Deletes the .db file and its backup directory for a given mindmap name."""
    db_path = get_add_on_db_path(mindmap_name)
    db_deleted = False

    if db_path and os.path.isfile(db_path):
        try:
            os.remove(db_path)
            db_deleted = True
        except OSError:
            db_deleted = False

    if backup_dir := get_mindmap_backup_path(mindmap_name):
        if os.path.isdir(backup_dir):
            try:
                rmtree(backup_dir)
            except OSError:
                pass

    return db_deleted


def rename_mindmap_file(old_mindmap_name: str, new_mindmap_name: str) -> bool:
    old_db_path = get_add_on_db_path(old_mindmap_name)
    new_db_path = get_add_on_db_path(new_mindmap_name)

    if not (old_db_path and new_db_path and os.path.isfile(old_db_path)):
        return False

    try:
        move(src=old_db_path, dst=new_db_path)
    except OSError as ose:
        showWarning(str(ose) + "Please report to Add on dev ! ")
        return False

    old_backup_dir = get_mindmap_backup_path(old_mindmap_name)
    new_backup_dir = get_mindmap_backup_path(new_mindmap_name)
    if old_backup_dir and new_backup_dir and os.path.isdir(old_backup_dir):
        try:
            move(src=old_backup_dir, dst=new_backup_dir)
        except OSError:
            pass

    return True


def export_mindmap_file(mindmap_name: str, destination_file_path: str) -> None:
    """
    Exports a single mindmap .db file to the provided destination path.
    """
    if not destination_file_path:
        raise ValueError("Destination file path is required.")

    source_file = get_add_on_db_path(mindmap_name)
    if not source_file or not os.path.isfile(source_file):
        raise FileNotFoundError(f"Mindmap '{mindmap_name}' was not found.")

    destination_directory = os.path.dirname(destination_file_path)
    if destination_directory:
        os.makedirs(destination_directory, exist_ok=True)

    copy2(source_file, destination_file_path)


def resolve_available_mindmap_name(preferred_name: str) -> tuple[str, bool]:
    candidate = preferred_name
    suffix = 2

    while True:
        candidate_path = get_add_on_db_path(candidate)
        if not candidate_path:
            raise OSError("Could not resolve local mindmap destination path.")
        if not os.path.exists(candidate_path):
            return candidate, candidate != preferred_name
        candidate = f"{preferred_name} ({suffix})"
        suffix += 1


def import_mindmap_file(source_file_path: str) -> tuple[str, bool]:
    """
    Imports a single mindmap .db file into local storage.

    :return: (imported_name, renamed_on_import)
    """
    if not source_file_path or not os.path.isfile(source_file_path):
        raise FileNotFoundError("Selected file does not exist.")
    if not source_file_path.lower().endswith(".db"):
        raise ValueError("Only .db files can be imported.")

    if not (mindmaps_storage_path := get_mindmaps_storage_path()):
        raise OSError("Could not resolve local mindmaps storage path.")
    os.makedirs(mindmaps_storage_path, exist_ok=True)

    preferred_name = os.path.splitext(os.path.basename(source_file_path))[0].strip()
    if not preferred_name:
        preferred_name = "Imported Mindmap"

    imported_name, renamed_on_import = resolve_available_mindmap_name(preferred_name)
    target_file_path = get_add_on_db_path(imported_name)
    if not target_file_path:
        raise OSError("Could not resolve destination path for imported mindmap.")

    copy2(source_file_path, target_file_path)
    return imported_name, renamed_on_import


def export_all_mindmaps(destination_directory: str) -> int:
    """
    Exports all mindmap .db files to the selected destination directory.

    :return: Number of exported files.
    """
    if not destination_directory:
        return 0

    source_directory = get_mindmaps_storage_path()
    if not source_directory or not os.path.isdir(source_directory):
        return 0

    os.makedirs(destination_directory, exist_ok=True)

    exported_count = 0
    for file_name in os.listdir(source_directory):
        if not file_name.endswith(".db"):
            continue

        source_file = os.path.join(source_directory, file_name)
        if not os.path.isfile(source_file):
            continue

        target_file = os.path.join(destination_directory, file_name)
        copy2(source_file, target_file)
        exported_count += 1

    return exported_count
