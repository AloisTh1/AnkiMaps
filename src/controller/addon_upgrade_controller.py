from ..repository.addon_upgrade_repository import AddonUpgradeRepository, UpgradeResult


class AddonUpgradeController:
    def __init__(self, repository: AddonUpgradeRepository):
        self.repository = repository

    def get_current_version(self) -> str:
        return self.repository.get_current_version()

    def upgrade_from_archive(self, archive_path: str) -> UpgradeResult:
        return self.repository.apply_package(archive_path)
