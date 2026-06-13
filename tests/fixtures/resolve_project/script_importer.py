"""Standalone script that imports the widgets module.

Lives OUTSIDE the ``mypackage`` package (top level of the fixture tree), so
``_get_import_path_for_file`` yields a path-derived handle (``script_importer``),
NOT a package module. Proves ``find_importers`` reports importers from
non-package / script-style files — the breadth the file-based scan buys.
"""

import mypackage._core.widgets

if __name__ == "__main__":
    print(mypackage._core.widgets.make_widget("script"))
