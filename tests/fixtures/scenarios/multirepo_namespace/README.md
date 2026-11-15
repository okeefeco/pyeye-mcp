# Multi-repo namespace scenario (#667)

A self-contained stand-in for a multi-repo PEP 420 workspace, so cross-repo
coverage doesn't depend on cloning external repos. Four sibling directories:

| Directory | Role | Layout |
|-----------|------|--------|
| `app/` | the main project (`project_path`) | its root **is** a package (`app/__init__.py`) |
| `corp-core/` | repo A, namespace portion `corp.core` | `src/` layout |
| `corp-tools/` | repo B, portion `corp.tools` | flat; configured through `packages` |
| `corp-web/` | repo C, portion `corp.web` | flat |

`app/.pyeye.json` wires the three repos in from **outside** the project root:
two through `namespaces`, one through `packages`. No directory has a
`corp/__init__.py`: `corp` is a PEP 420 namespace stitched across three repos.

Cross-repo relationships it exercises:

- a subclass across repos: `corp.tools.widgets.Widget(corp.core.models.Base)`;
- calls into two other repos: `corp.web.views.render` calls `corp.core.models.make`
  and `corp.tools.widgets.Widget`;
- a re-export: `corp.tools` re-exports `corp.core.models.Base`;
- an aliased import, a `TYPE_CHECKING` import, a lazy import inside a function;
- a nested module: `corp.tools.sub.helper`;
- a name collision: `Shared` is defined in both `corp.core.models` and
  `corp.tools.widgets`;
- one stdlib import per repo.

Tests build on a temporary copy of this whole directory, so the relative paths in
`.pyeye.json` keep working and nothing is written here.
