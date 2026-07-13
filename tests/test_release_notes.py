import unittest

from src.common.release_notes import build_release_notes, compare_versions


CHANGELOG = """# CHANGELOG

<!-- version list -->

## v2.7.0 (2026-07-13)

### Features

- Add release news
  ([`abc1234`](https://example.com/commit/abc1234))

### Bug Fixes

- Handle filtered deck errors

## v2.6.0 (2026-05-24)

### Features

- Add news box
"""


class ReleaseNotesTest(unittest.TestCase):
    def test_first_tracked_launch_shows_current_release(self):
        text, has_unseen_news = build_release_notes(CHANGELOG, "2.7.0", "")

        self.assertTrue(has_unseen_news)
        self.assertIn("Latest changes in v2.7.0", text)
        self.assertIn("Add release news", text)
        self.assertNotIn("Add news box", text)
        self.assertNotIn("abc1234", text)

    def test_upgrade_shows_every_release_since_last_seen_version(self):
        text, has_unseen_news = build_release_notes(CHANGELOG, "2.7.0", "2.5.0")

        self.assertTrue(has_unseen_news)
        self.assertIn("Changes since v2.5.0", text)
        self.assertIn("v2.7.0", text)
        self.assertIn("v2.6.0", text)

    def test_same_version_does_not_open_news_automatically(self):
        text, has_unseen_news = build_release_notes(CHANGELOG, "2.7.0", "2.7.0")

        self.assertFalse(has_unseen_news)
        self.assertIn("Latest changes in v2.7.0", text)
        self.assertNotIn("v2.6.0", text)

    def test_empty_changelog_has_fallback(self):
        self.assertEqual(
            build_release_notes("", "2.7.0", "2.6.0"),
            ("No release notes are available for this build.", False),
        )

    def test_versions_are_compared_numerically(self):
        self.assertGreater(compare_versions("2.10.0", "2.9.0"), 0)
        self.assertEqual(compare_versions("v2.7", "2.7.0"), 0)


if __name__ == "__main__":
    unittest.main()
