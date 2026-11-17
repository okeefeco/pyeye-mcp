# docs_examples_django fixture

A small Django project for the executed examples in `docs/api/django-tools.md`
(#830). Examples reach it with `fixture=docs_examples_django`. Like
`docs_examples`, change it only together with the examples that depend on it:
`uv run pytest tests/test_docs_examples.py` shows which ones.
