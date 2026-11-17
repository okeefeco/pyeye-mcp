# Security Policy

## Supported Versions

Security fixes are released for the latest major version only.

| Version | Supported |
|---------|-----------|
| 2.x     | ✅ Yes    |
| 1.x     | ❌ No: upgrade to 2.x (see the CHANGELOG migration map) |
| < 1.0   | ❌ No     |

## Reporting a Vulnerability

**Please do not report security vulnerabilities in public issues, discussions or
pull requests.**

Report them privately through GitHub:
**[Report a vulnerability](https://github.com/okeefeco/pyeye-mcp/security/advisories/new)**
(the repository's Security tab → *Report a vulnerability*). This opens a draft
advisory that only you and the maintainers can see.

Please include:

- the affected version (`pip show pyeye-mcp`, or the commit if running from source)
- what an attacker can do, and what they need to be able to control (for
  example the analysed source tree, the MCP client's tool arguments, or a
  configuration file)
- steps to reproduce, ideally a minimal project or tool call
- any suggested fix or mitigation

## What to Expect

This is a small, maintainer-run project with no service-level commitment. What
we aim for:

- **Acknowledgement:** we reply on the advisory as soon as we've seen it.
- **Assessment:** we tell you whether we can reproduce the issue, and how severe
  we think it is.
- **Fix:** a patch release for confirmed issues as soon as one is ready, with
  the advisory published at the same time. You'll be credited in the advisory
  unless you prefer not to be.

Please give us a reasonable chance to release a fix before disclosing publicly.

## Scope

### In scope

Vulnerabilities in pyeye itself, for example:

- reading or writing files outside what the user asked pyeye to analyse,
  beyond the documented behaviour below
- code execution triggered by analysing a project's source
- injection through MCP tool arguments, configuration files or analysed source
- a vulnerable dependency that is actually exploitable through pyeye

### Out of scope

- issues that need an attacker who already controls the machine or the user's
  account
- findings from automated scanners with no demonstrated impact on pyeye
- vulnerabilities in dependencies that pyeye's usage doesn't expose (report
  those upstream)

## Security Model

How pyeye behaves, so you can judge what counts as a vulnerability:

- **Static analysis only.** pyeye parses and analyses Python source with
  [Jedi](https://github.com/davidhalter/jedi). It doesn't import or run the
  analysed project's code, and the server starts no subprocess of its own.
  Jedi starts one helper subprocess: the server's own Python interpreter running
  a script from Jedi's package, without a shell. Jedi uses it to introspect
  compiled modules, and imports them only from the server's Python environment.
  pyeye leaves Jedi's `load_unsafe_extensions` off, so compiled extensions
  inside the analysed project or a configured package are never loaded.
- **It reads what the MCP client points it at.** Tools take a `project_path`,
  and `configure_packages` can add package, namespace and standalone-script
  paths. pyeye reads those paths with the permissions of the user running the
  server. Some path inputs are checked: null bytes and `...` are rejected, and so
  is a path naming one of a few system directories (`/etc/`, `/root/`, `/proc/`,
  `/sys/`, `/dev/`). This is a sanity check, **not a sandbox**:
  - any directory the server's user can read can be analysed if a client asks
    for it;
  - not every path input goes through the check, and a relative path or a
    symlink isn't checked in the form that's finally read
    ([#856](https://github.com/okeefeco/pyeye-mcp/issues/856) tracks closing
    those gaps).

  Run the server as a user whose read access you're comfortable exposing to your
  MCP client.
- **What it writes:**
  - `configure_packages` writes `.pyeye.json` in the `project_path` it was given,
    replacing any existing one, whenever the call adds packages, namespaces or
    standalone directories. `save` defaults to `true`; pass `save=false` to change
    the running configuration only. The file holds the project's whole merged
    configuration, not just the keys the call added.
  - Usage metrics go to `~/.pyeye/metrics/`: per server session, the tool names
    called, call counts, durations, error counts and timestamps. No tool
    arguments, paths or source are recorded.
  - Logs go to the file named by `PYEYE_LOG_FILE`, if it's set.

  It doesn't modify the analysed source.
- **No network access** is needed for analysis, and the server makes no
  network requests.

## Security Checks in Development

The pre-commit hooks run `detect-secrets` and `bandit` on every commit, and
`pip-audit` (against the locked dependency set) whenever `pyproject.toml` or
`uv.lock` changes. CI runs all three on every pull request. See
[CONTRIBUTING.md](CONTRIBUTING.md).
