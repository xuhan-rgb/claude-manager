# Repository Guidelines

## Project Structure & Module Organization
- `src/claude_manager/`: core package. Key modules include `app.py` (Textual TUI), `cli.py` (entry point), `launcher.py` (split layout startup), `kitty_control.py` and `tmux_control.py` (integrations), and `data_store.py` (JSON persistence).
- `tests/`: pytest suite (currently `test_models.py`).
- `config/layouts/`: user layout presets (loaded at runtime).
- Root docs: `README.md`, `CLAUDE.md`, `COMMANDS.md` for usage, architecture, and debugging.

## Build, Test, and Development Commands
- `pip install -e .`: install the package in editable mode.
- `pip install -e ".[dev]"`: install dev deps (pytest, pytest-asyncio).
- `claude-manager`: run the TUI with default split layout.
- `claude-manager --check`: validate Kitty/tmux environment setup.
- `pytest`: run tests.
- `./watch_logs.sh` or `tail -f ~/.config/claude-manager/logs/app.log`: follow runtime logs.

## Coding Style & Naming Conventions
- Python 3.10+ with PEP 8 conventions: 4-space indentation, snake_case for functions/vars, PascalCase for classes, and UPPER_SNAKE_CASE for constants.
- No formatter/linter config is defined in-repo; keep formatting consistent with existing modules in `src/claude_manager/`.
- Prefer explicit, small methods for integrations (Kitty/tmux) and keep side effects isolated to controller modules.

## Testing Guidelines
- Framework: pytest (see `tests/test_models.py`).
- Naming: files `test_*.py`, tests `test_*`.
- Coverage: no explicit threshold configured; add tests for new behaviors and persistence changes.

## Commit & Pull Request Guidelines
- Git history is not available in this workspace, so no established commit style can be inferred. Use concise, imperative subjects (or Conventional Commits like `feat:`/`fix:`) and include the scope if helpful.
- PRs should include: clear description, rationale, how to run/verify, and tests run. Attach logs or CLI output for behavior changes, especially around Kitty/tmux integration.

## Configuration & Runtime Notes
- Requires Kitty remote control enabled and tmux installed. See `README.md`/`CLAUDE.md` for exact config snippets.
- Data is persisted under `~/.local/share/claude-manager/`; logs under `~/.config/claude-manager/logs/`.
