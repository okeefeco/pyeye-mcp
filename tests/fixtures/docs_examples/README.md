# docs_examples fixture

The project that executed documentation examples run against (#828). Tagged
` ```json pyeye-example ` blocks in the registered docs call pyeye on this
project. The package is named `myapp` because the skills use `myapp.…` as their
placeholder project, so those examples run as written.

Change it only together with the examples that depend on it:
`uv run pytest tests/test_docs_examples.py` shows which ones.
