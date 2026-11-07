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

This is a small, maintainer-run project, so these timelines are goals rather
than guarantees:

- **Acknowledgement** within 7 days.
- **Assessment** (confirmed or not, and its severity) within 14 days.
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
  analysed project's code. The only subprocess it starts is `ripgrep` for text
  search, invoked without a shell.
- **It reads what the MCP client points it at.** Tools take a `project_path`,
  and `configure_packages` can add further package paths. pyeye reads those
  paths with the permissions of the user running the server. Path inputs are
  validated (null bytes, `...` and a small deny-list of system directories such
  as `/etc/` and `/proc/` are rejected), but this is a sanity check, **not a
  sandbox**: any directory the server's user can read can be analysed if a
  client asks for it. Run the server as a user whose read access you're
  comfortable exposing to your MCP client.
- **What it writes:**
  - `configure_packages(save=True)` writes `.pyeye.json` in the server's
    working directory
  - usage metrics are stored under `~/.pyeye/`
  - logs go to `PYEYE_LOG_FILE`, if set

  It doesn't modify the analysed source.
- **No network access** is needed for analysis.

## Security Checks in Development

Every commit runs `detect-secrets`, `bandit` and `pip-audit` (against the locked
dependency set) as pre-commit hooks, and CI runs them again. See
[CONTRIBUTING.md](CONTRIBUTING.md).
