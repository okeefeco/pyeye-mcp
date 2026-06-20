"""Standalone script using the ``from package import submodule`` idiom.

Lives at the fixture root, OUTSIDE ``mypackage``, so its path-derived handle
(``submod_script_importer``) shares no top-level package with the target. The
textual pre-filter therefore cannot admit it via ``shares_package`` — only the
parent-package trigger (``mypackage._core`` appearing in the source) lets the
authoritative AST check run. This exercises the cross-package half of the #436
fix (the pre-filter widening), distinct from the same-package
``submod_importer``.
"""

from mypackage._core import widgets

if __name__ == "__main__":
    print(widgets.make_widget("submod-script"))
