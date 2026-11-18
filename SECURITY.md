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

How pyeye behaves, so you can judge what counts as a vulnerability. The values
in this section are generated from pyeye's code (`scripts/docs_facts.py`), so
they can't drift from it.

- **Static analysis only.** pyeye parses and analyses Python source with
  [Jedi](https://github.com/davidhalter/jedi). It doesn't import or run the
  analysed project's code. Calls in the server's code that start a process:
  <!-- fact:begin security.subprocesses -->none<!-- fact:end -->.
  Jedi itself runs a helper process, the server's own Python interpreter, to
  introspect compiled modules. pyeye's Jedi setting `load_unsafe_extensions` is
  <!-- fact:begin security.jedi_unsafe_extensions -->off<!-- fact:end -->, so Jedi
  loads compiled extensions only from the server's Python environment, never
  from the analysed project or a configured package.
- **It reads what the MCP client points it at.** Tools take a `project_path`,
  and `configure_packages` can add package, namespace and standalone-script
  paths. pyeye reads those paths with the permissions of the user running the
  server.

  Every caller-supplied path goes through the input check in the form the tool
  will finally use: a relative path anchored on the call's `project_path` (or,
  for `project_path` itself, on the server's working directory), checked both as
  spelled and with symlinks followed
  ([#856](https://github.com/okeefeco/pyeye-mcp/issues/856)). That covers:

  - `project_path`, and `resolve_at`'s `file`;
  - `resolve`'s file forms (`path/to/file.py` and `path/to/file.py:42`);
  - a plugin tool's `scope="package:<path>"`;
  - `configure_packages`' `packages`, `namespaces` paths and `standalone_dirs`;
  - the `namespaces` and `standalone.dirs` paths in a `.pyeye.json` or other
    config, which are skipped with a warning when refused, rather than failing
    the call.

  A refused tool argument is an error, never a "not found". A path is rejected
  for:

  <!-- fact:begin security.path_checks -->
  - anywhere in the path: null bytes, suspicious triple dots;
  - a target matching one of these anchored patterns, ignoring case: `^/etc/`, `^/private/etc/`, `^/root/`, `^/proc/`, `^/sys/`, `^/dev/`, `^/boot/`, `^/run/secrets/`, `^/var/run/secrets/`, `^/var/root/`, `^/private/var/root/`;
  - a credential store directly below a user home, or anything inside it, ignoring case: `.ssh`, `.aws`, `.gnupg`, `.config/gcloud`, `.azure`, `.kube`, `.docker`, `.config/gh`, `.netrc`, `.pypirc`, `.pgpass`, `.git-credentials`, `.npmrc`; a user home is one of `^/home/[^/]+/`, `^/Users/[^/]+/`, `^/root/`, or the server's own home;
  - forms checked: the deny-list checks the target's lexical and resolved forms.
  <!-- fact:end -->

  A directory pyeye scans (a plugin scope, or a configured package, namespace
  or standalone directory) is also refused when it is an ancestor of one of the
  anchored directories above:
  <!-- fact:begin security.path_checks.ancestors -->`/`, `/private`, `/private/var`, `/run`, `/var`, `/var/run`<!-- fact:end -->. That includes the
  scan `project_path="/"` implies for scope `main`. `project_path` itself and
  single-file inputs are not affected. Every directory walk also skips a
  directory whose resolved form is one of them, so a symlink inside a scanned
  tree can't lead a walk into one.

  The credential stores are different: they define no ancestors. A scan of
  `~`, `/home` or `/Users` works and simply skips them. A project placed inside
  one, such as a repository at `~/.config/gh/x`, is refused, as intended. A
  user home is matched by pattern, so a home created after the server started
  is covered too. The server's own home is read once, when the process starts:
  a `$HOME` outside `/home`, `/Users` and `/root` (for example
  `/var/lib/jenkins`) is covered for the server's own user, but other users'
  homes there are not (#909).

  A directory merely named like one of these inside another path, such as
  `~/dev/proj`, `/srv/etc/lib` or a project's own `etc/` package, is not
  refused: only where the path leads counts (#939).

  The patterns are POSIX system paths. On Windows a resolved path starts with a
  drive letter, so they never match it. This is a sanity check, **not a
  sandbox**:
  - any directory the server's user can read can be analysed if a client asks
    for it;
  - the check is the deny-list above, nothing more: any other directory the
    server's user can read is in reach.

  Run the server as a user whose read access you're comfortable exposing to your
  MCP client.
- **What it writes.** Every place in the server's code that writes a file or
  creates a directory:
  <!-- fact:begin security.write_sites -->`pyeye.config:ProjectConfig.save_config`, `pyeye.config:create_example_config`, `pyeye.mcp.__main__:_configure_logging`, `pyeye.unified_metrics:UnifiedMetricsCollector.__init__`, `pyeye.unified_metrics:UnifiedMetricsCollector._append_jsonl`, `pyeye.unified_metrics:UnifiedMetricsCollector._write_json`, `pyeye.unified_metrics:UnifiedMetricsCollector.cleanup_old_sessions`, `pyeye.unified_metrics:UnifiedMetricsCollector.export_metrics`<!-- fact:end -->.
  Among them, the files the server keeps:
  - the project configuration,
    <!-- fact:begin security.writes.config -->`<project_path>/.pyeye.json`<!-- fact:end -->, when
    `configure_packages` adds packages, namespaces or standalone directories.
    The parameter and its default:
    <!-- fact:begin tool.configure_packages.param.save -->`save`: true<!-- fact:end -->;
    pass `save=false` to change only the running configuration;
  - usage metrics, under <!-- fact:begin security.writes.metrics -->`~/.pyeye/metrics/`<!-- fact:end -->.
    A tool call hands the metrics recorder only
    <!-- fact:begin security.metrics_inputs -->`tool_name`, `session_id`, `success`, `duration_ms`<!-- fact:end -->, so no tool
    arguments, paths or source reach it;
  - logs, to the file named by
    <!-- fact:begin env.PYEYE_LOG_FILE -->`PYEYE_LOG_FILE`<!-- fact:end -->, if it's set.

  None of these writes the analysed source files.
- **No network access** is needed for analysis. Imports of a networking module
  in the server's code: <!-- fact:begin security.network_imports -->none<!-- fact:end -->.

## Security Checks in Development

The pre-commit hooks run <!-- fact:begin precommit.hook.detect-secrets -->`detect-secrets`<!-- fact:end -->
and <!-- fact:begin precommit.hook.bandit -->`bandit`<!-- fact:end --> on every commit, and
<!-- fact:begin precommit.hook.pip-audit -->`pip-audit`<!-- fact:end --> (against the locked dependency set) whenever `pyproject.toml` or
`uv.lock` changes. CI runs all three on every pull request. See
[CONTRIBUTING.md](CONTRIBUTING.md).
