# AnkiMaps

AnkiMaps brings mind maps directly into Anki so you can visualize concepts, connect ideas, and review with better context.

## What You Can Do

- Build and organize mind maps around your Anki notes.
- Create visual links between notes with styled connections and labels.
- Start focused review sessions from the current map only.
- Keep context during review with map-level highlighting.
- Customize note display, connection style, and layout behavior.

## First Installation

1. Download the `.ankiaddon` package.
2. In Anki, open `Tools` -> `Add-ons`.
3. Drag and drop the `.ankiaddon` file into the Add-ons window.
4. Restart Anki.

## Data Storage

AnkiMaps stores persistent data inside the add-on directory:

- `addons21/AnkiMaps/user_files/mindmaps/*.db`
- `addons21/AnkiMaps/user_files/backups/...`

It does not store app data in the Anki profile directory.

## Development Packaging

Build a local package with:

```powershell
python package.py
```

Output artifact:

- `dist/AnkiMaps_<version>.ankiaddon`

Package notes:

- No top-level wrapper folder in the archive.
- `__pycache__`, `*.pyc`, and `*.pyo` are excluded from packaging.

## Release Automation

Releases are automated on pushes to `main` through `.github/workflows/release.yml`.
`python-semantic-release` computes the version, builds the `.ankiaddon`, and uploads assets to the GitHub release.

Use conventional commits so semantic-release can version correctly, for example:

- `fix: ...`
- `feat: ...`
- `docs: ...`

## License

AnkiMaps is free and open-source software under the MIT license.
See `LICENSE.txt` for the full text.

## Support

For support, bug reports, or feature requests, please contact:
**alois [dot] devlp [at] gmail [dot] com**

## Author

- Alois Thibert
- GitHub: <https://github.com/AloisTh1/AnkiMaps>
