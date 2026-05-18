# Testing

Test the plugin by running `claude --plugin-dir ./noticed` against real projects. Use `claude --debug` for plugin loading and hook execution logs.

Automated tests live in `tests/` and run with `pytest`. They cover security invariants, the transcript analyzer, cache manager, and proposal builder. Run with `python3 -m pytest tests/ -v`. Pytest is a dev-only dependency — runtime scripts use only the standard library.

Run pytest after completing each logical unit of work — not after every edit. Always run the full suite before committing.
