# Repository Guidelines

## Project Structure & Module Organization

AnkiMaps is a Python 3.9 desktop add-on. The root `__init__.py` wires Anki hooks, windows, and controllers. Application code lives under `src/`:

- `src/view/`: PyQt windows, widgets, graphics items, and UI assets.
- `src/controller/`: user-flow orchestration, commands, and history handling.
- `src/model/`: mind-map state, nodes, and connections.
- `src/repository/`: Anki APIs, SQLite persistence, backups, and file access.
- `src/common/`: shared constants, utilities, IO, and spatial indexing.

Packaging artwork is in `assets/packaging/`; generated add-ons go to `dist/`. Read `ARCHITECTURE.md` before changing layer boundaries.

## Build, Test, and Development Commands

- `uv sync --frozen`: install the locked Python 3.9 dependencies.
- `uv run pre-commit run --all-files`: run whitespace, YAML, Ruff, formatting, and secret checks.
- `uv run ruff check .`: lint Python sources; add `--fix` for safe fixes.
- `uv run ruff format --check .`: verify formatting without rewriting files.
- `uv run python deploy.py`: copy the working add-on into the local Anki add-ons directory for manual testing.
- `uv run python package.py`: create `dist/AnkiMaps_<version>.ankiaddon`.

Close Anki before deploying. `deploy.py --delete` removes the installed development copy.

## Coding Style & Naming Conventions

Use four-space indentation and Ruff formatting with a 110-character line limit. Follow Python conventions: `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants. Keep UI behavior in views, workflow decisions in controllers, domain state in models, and external IO in repositories. Add type hints to public or non-obvious interfaces.

## Testing Guidelines

There is no committed automated test suite or coverage threshold. Run pre-commit and smoke-test every change in Anki. Exercise map creation/loading, edits, persistence after restart, and affected shortcuts or dialogs. Add future tests under `tests/`, mirror the source layout, and name files `test_<module>.py`.

## Commit & Pull Request Guidelines

Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`); semantic-release uses them to determine versions. Keep commits focused and avoid committing `dist/`, caches, local databases, or Playwright state. Pull requests should explain user-visible impact, list validation performed, link related issues, and include screenshots or a short recording for UI changes. Call out database or user-file migration risks explicitly.

## Security & Release Notes

Never commit credentials, AnkiWeb session data, or user mind-map databases. Publishing and semantic-release change external state; run them only when explicitly preparing a release.
