# Changelog fragments

Each user-facing PR adds one file here instead of editing `CHANGELOG.md`:

```text
changes/<issue>.<category>.md      e.g. changes/619.fixed.md
changes/<issue>-<n>.<category>.md  a second PR for the same issue, e.g. 623-2.fixed.md
```

The categories, with the `CHANGELOG.md` heading each one fills, are:

| Category     | Heading                 |
|--------------|-------------------------|
| `breaking`   | `### BREAKING CHANGES`  |
| `added`      | `### Added`             |
| `changed`    | `### Changed`           |
| `deprecated` | `### Deprecated`        |
| `removed`    | `### Removed`           |
| `fixed`      | `### Fixed`             |
| `security`   | `### Security`          |

A fragment holds one or more `-` bullets, written by hand like any other
CHANGELOG entry. It has no heading, because the category is in the file name.

`python scripts/changelog.py prepare X.Y.Z` collects the fragments into the
release section and deletes them (see `docs/RELEASE.md`), and
`python scripts/changelog.py check` validates their names in CI. This README is
not a fragment.
