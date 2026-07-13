import re
from typing import TypedDict


class ChangelogRelease(TypedDict):
    version: str
    date: str
    body: str


def build_release_notes(
    changelog_text: str,
    current_version: str,
    last_seen_version: str,
) -> tuple[str, bool]:
    releases = parse_changelog_releases(changelog_text)
    if not releases:
        return ("No release notes are available for this build.", False)

    has_unseen_news = current_version != "unknown" and (
        not last_seen_version or compare_versions(last_seen_version, current_version) < 0
    )
    selected_releases = select_changelog_releases(
        releases,
        current_version=current_version,
        last_seen_version=last_seen_version,
    )
    title = (
        f"Changes since v{last_seen_version}"
        if last_seen_version and has_unseen_news
        else f"Latest changes in v{current_version}"
    )
    return (format_changelog_releases(title, selected_releases), has_unseen_news)


def parse_changelog_releases(changelog_text: str) -> list[ChangelogRelease]:
    release_header = re.compile(r"^## v(?P<version>\d+(?:\.\d+){1,2})(?: \((?P<date>[^)]+)\))?", re.M)
    matches = list(release_header.finditer(changelog_text))
    releases: list[ChangelogRelease] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(changelog_text)
        body = clean_changelog_body(changelog_text[body_start:body_end])
        if body:
            releases.append(
                {
                    "version": match.group("version"),
                    "date": match.group("date") or "",
                    "body": body,
                }
            )
    return releases


def clean_changelog_body(body: str) -> str:
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("([`"):
            continue
        line = re.sub(r"\s+\(\[`[0-9a-f]+`]\([^)]+\)\)", "", line)
        if line.startswith("### "):
            line = line[4:]
        lines.append(line)
    return "\n".join(lines)


def select_changelog_releases(
    releases: list[ChangelogRelease],
    current_version: str,
    last_seen_version: str,
) -> list[ChangelogRelease]:
    if current_version == "unknown":
        return releases[:1]
    if last_seen_version and compare_versions(last_seen_version, current_version) < 0:
        selected = [
            release
            for release in releases
            if compare_versions(release["version"], last_seen_version) > 0
            and compare_versions(release["version"], current_version) <= 0
        ]
        return selected or releases[:1]
    return [release for release in releases if release["version"] == current_version] or releases[:1]


def format_changelog_releases(title: str, releases: list[ChangelogRelease]) -> str:
    blocks = [title]
    for release in releases:
        release_title = f"v{release['version']}"
        if release["date"]:
            release_title = f"{release_title} ({release['date']})"
        blocks.append(f"{release_title}\n{release['body']}")
    return "\n\n".join(blocks)


def compare_versions(left: str, right: str) -> int:
    left_parts = version_parts(left)
    right_parts = version_parts(right)
    return (left_parts > right_parts) - (left_parts < right_parts)


def version_parts(version: str) -> tuple[int, ...]:
    numeric_version = version.lstrip("v")
    parts = []
    for value in numeric_version.split("."):
        try:
            parts.append(int(value))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])
