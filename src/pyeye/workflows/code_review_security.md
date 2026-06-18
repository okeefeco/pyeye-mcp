# Python Security Code Review (OWASP 2025)

> Tool mechanics (call signatures, return shapes, edges) live in the python-explore skill
> (`skills/python-explore/SKILL.md`). This playbook names the tools to reach for; the skill
> is the source of truth for how to drive them.

## Goal

Identify security vulnerabilities in Python code using OWASP guidelines and PyEye's semantic analysis to validate input handling, map structural relationships, and detect security anti-patterns.

## A Hard Limit Before You Start: Reverse References

Security review leans on "who calls this?" and "what references this tainted value?" —
full reverse data-flow. **PyEye cannot answer that reliably yet.** Caller/reference edges
are deferred to the Pyright backend ([#333](https://github.com/okeefeco/pyeye-mcp/issues/333));
PyEye refuses them rather than returning a wrong or under-reported set.

So you **cannot statically confirm complete taint flow** (every path from a source to a
sink) with PyEye today. What you *can* do reliably:

- **Forward** from a function: `expand(edge="callees")` / `trace(follow=["callees"])` — what
  a handler calls downstream toward a sink.
- **Around a module:** `expand(edge="imported_by")` (who imports it) and
  `expand(edge="imports")` (what it pulls in).
- **Inheritance:** `expand(edge="subclasses")` / `expand(edge="superclasses")`.
- **Structure:** `inspect`, `outline`, `expand(edge="members")`, `expand(edge="enclosing_scope")`.

When a step below wants reverse data ("trace back to where input comes from"), say so
plainly and substitute forward edges plus a `grep`-anchored manual read of the call sites —
and treat the result as **unconfirmed**, not exhaustive.

## When to Use This Workflow

- Security audit of new code
- Pre-production security review
- High-risk code changes (authentication, data handling, API endpoints)
- Compliance requirements
- After security vulnerability reports

## Security Review Methodology

Combines:

- **Automated scanning** - SAST tools, dependency checks
- **Manual review** - OWASP checklist
- **Semantic analysis** - MCP tools for data flow tracing

## Steps

1. **Automated Scanning** - Run security tools (bandit, pip-audit, safety, detect-secrets)
2. **Input Validation Review** - Map user-input handlers and their forward call structure
3. **Authentication/Authorization Review** - Find and verify auth patterns
4. **Data Flow Analysis** - Follow forward edges (`trace`/`expand callees`) toward sinks
5. **Framework-Specific Review** - Use framework plugins (Flask/Django)
6. **Review OWASP checklist** - Verify all security categories below

See "Security Review Workflow" section for detailed process.

## OWASP Security Checklist

### 1. Input Validation

**Critical**: All external input must be validated

**Review Points**:

- [ ] All user input is validated before use
- [ ] Whitelist validation preferred over blacklist
- [ ] Input length and type constraints enforced
- [ ] Special characters properly handled
- [ ] File uploads validated (type, size, content)

**PyEye - Map Input Flow (forward only)**:

- `resolve` the input handler to a canonical handle.
- `expand(edge="callees")` or `trace(follow=["callees"])` to see where input flows
  downstream — toward validators and sinks.
- Reverse ("who sends input *into* this handler?") is **not available** (#333). To check
  call sites, `grep` for the handler name and `Read` each one manually; treat the set as
  unconfirmed, not exhaustive.

**Common Vulnerabilities**:

```python
# ❌ DANGEROUS - No validation
def update_user(user_id):
    db.execute(f"UPDATE users SET name = '{request.form['name']}' WHERE id = {user_id}")

# ✅ SAFE - Validated input with parameterized query
def update_user(user_id: int):
    name = validate_name(request.form.get('name', ''))
    if not name:
        raise ValidationError("Invalid name")
    db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
```

### 2. SQL Injection Prevention

**Requirements**:

- [ ] Always use parameterized queries
- [ ] Never build SQL with string concatenation
- [ ] Use ORM when possible (SQLAlchemy, Django ORM)
- [ ] Validate numeric inputs are actually numeric

**Detection Strategy**:

- `resolve` the DB execute wrapper, then `expand(edge="imported_by")` to find which modules
  use it — those are your audit surface.
- For each caller module, `outline` it and `Read` the execute call sites to check whether
  SQL is built from user input. Reverse "trace back to the input source" is not statically
  available (#333); confirm by reading the call sites, not by trusting a reference query.

**Examples**:

```python
# ❌ VULNERABLE - String concatenation
query = f"SELECT * FROM users WHERE id = {user_id}"
db.execute(query)

# ❌ VULNERABLE - String formatting
query = "SELECT * FROM users WHERE name = '{}'".format(name)
db.execute(query)

# ✅ SAFE - Parameterized query
db.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# ✅ SAFE - ORM
User.query.filter_by(id=user_id).first()
```

### 3. Command Injection Prevention

**Requirements**:

- [ ] Avoid `os.system()`, `subprocess.shell=True`
- [ ] Use subprocess with list arguments
- [ ] Validate/sanitize all input to shell commands
- [ ] Use libraries instead of shell commands when possible

**PyEye - Find Command Execution**:

- `expand("subprocess", edge="imported_by")` to find every project module that imports
  `subprocess` (likewise for `os`).
- `inspect` the call sites' enclosing functions and `Read` them to verify `shell=False`
  and list-form arguments.

**Examples**:

```python
# ❌ DANGEROUS - Shell injection possible
import os
os.system(f"ls {user_directory}")

# ❌ DANGEROUS - Shell=True with user input
subprocess.run(f"grep {pattern} {file}", shell=True)

# ✅ SAFE - List arguments, no shell
subprocess.run(["ls", user_directory], shell=False)

# ✅ BETTER - Use library instead
import os
os.listdir(user_directory)
```

### 4. Path Traversal Prevention

**Requirements**:

- [ ] Validate file paths are within allowed directories
- [ ] Resolve paths before validation (`Path.resolve()`)
- [ ] Never trust user-provided file paths
- [ ] Use `Path` objects, not string manipulation

**PyEye - Find File Operations**:

- `resolve` the file-reading helper and `expand(edge="callees")` to confirm it routes
  through path-validation/resolution before `open`.
- Reverse ("where do the file paths originate?") is not statically available (#333);
  `grep` the helper name and `Read` each call site to check the path is validated.

**Examples**:

```python
# ❌ VULNERABLE - No path validation
def read_user_file(filename):
    with open(f"/app/uploads/{filename}") as f:
        return f.read()
# Attacker: filename = "../../../etc/passwd"

# ✅ SAFE - Path validation
from pathlib import Path

def read_user_file(filename: str):
    base = Path("/app/uploads").resolve()
    file_path = (base / filename).resolve()

    # Ensure file is within allowed directory
    if not str(file_path).startswith(str(base)):
        raise SecurityError("Path traversal detected")

    with open(file_path) as f:
        return f.read()
```

### 5. Authentication & Authorization

**Requirements**:

- [ ] Passwords hashed with modern algorithm (bcrypt, argon2)
- [ ] Never store passwords in plain text
- [ ] Session tokens cryptographically random
- [ ] Authorization checked on every protected resource
- [ ] No authentication logic in frontend only

**PyEye - Find Auth Patterns**:

- `resolve` the auth entry points (`authenticate`, `login`) to canonical handles, then
  `inspect`/`outline` to see their structure and `expand(edge="callees")` to confirm they
  reach a hashing/verify routine.
- Confirming that *every* protected resource checks authorization needs reverse references,
  which are not available (#333). Enumerate protected entry points another way — for Flask,
  the `find_routes()` plugin tool lists routes so you can audit each for an auth decorator —
  then `Read` each handler.

**Examples**:

```python
# ❌ DANGEROUS - Plain text password
def create_user(username, password):
    db.execute("INSERT INTO users (name, password) VALUES (?, ?)",
               (username, password))

# ❌ DANGEROUS - Weak hashing
import hashlib
password_hash = hashlib.md5(password.encode()).hexdigest()

# ✅ SAFE - Modern password hashing
import bcrypt

def create_user(username: str, password: str):
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    db.execute("INSERT INTO users (name, password_hash) VALUES (?, ?)",
               (username, password_hash))

# ✅ SAFE - Verify authorization
def get_document(doc_id: int, user: User):
    doc = Document.get(doc_id)
    if not doc.is_accessible_by(user):
        raise AuthorizationError("Access denied")
    return doc
```

### 6. Cryptography

**Requirements**:

- [ ] Use standard crypto libraries (cryptography, hashlib)
- [ ] Never implement custom crypto algorithms
- [ ] Use proper random number generation (`secrets` module)
- [ ] Appropriate key sizes (AES-256, RSA-2048+)

**Examples**:

```python
# ❌ DANGEROUS - Weak randomness
import random
token = random.randint(1000, 9999)

# ❌ DANGEROUS - Custom crypto
def my_encrypt(data):
    # Custom XOR cipher - NEVER DO THIS!
    ...

# ✅ SAFE - Cryptographically secure random
import secrets
token = secrets.token_urlsafe(32)

# ✅ SAFE - Standard library crypto
from cryptography.fernet import Fernet
key = Fernet.generate_key()
cipher = Fernet(key)
encrypted = cipher.encrypt(data.encode())
```

### 7. Sensitive Data Exposure

**Requirements**:

- [ ] No secrets in code (API keys, passwords)
- [ ] Use environment variables or secret management
- [ ] Sensitive data encrypted at rest
- [ ] Logs don't contain sensitive data
- [ ] Error messages don't leak information

**Automated Detection**:

```bash
# Run detect-secrets (should be in pre-commit)
detect-secrets scan

# Search for common patterns
ruff check --select S  # Security rules
bandit -r src/         # Security linter
```

**PyEye - Find Hardcoded Secrets**:

- `resolve` suspect constants (`API_KEY`, `SECRET`, `PASSWORD`) to their definition handles,
  then `inspect` each to see kind/location and `Read` the line to confirm it loads from
  `os.environ` or a config/secret system rather than a literal.
- Pair this with `detect-secrets` / `bandit` (below) for pattern coverage PyEye doesn't do.

**Examples**:

```python
# ❌ DANGEROUS - Hardcoded secret
API_KEY = "sk-1234567890abcdef"  # pragma: allowlist secret
db_password = "MyP@ssw0rd123"  # pragma: allowlist secret

# ✅ SAFE - Environment variables
import os
API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    raise ConfigurationError("API_KEY not configured")

# ✅ SAFE - Secret management
from azure.keyvault.secrets import SecretClient
secret = secret_client.get_secret("api-key").value
```

### 8. XML/JSON External Entities (XXE)

**Requirements**:

- [ ] Disable external entity processing in XML parsers
- [ ] Validate JSON structure before parsing
- [ ] Limit JSON/XML size to prevent DoS

**Examples**:

```python
# ❌ VULNERABLE - Default XML parser allows XXE
import xml.etree.ElementTree as ET
tree = ET.parse(user_provided_xml)

# ✅ SAFE - Disable external entities
import defusedxml.ElementTree as ET
tree = ET.parse(user_provided_xml)

# ✅ SAFE - JSON size limit
import json
MAX_JSON_SIZE = 1_000_000  # 1MB
if len(json_string) > MAX_JSON_SIZE:
    raise ValidationError("JSON too large")
data = json.loads(json_string)
```

### 9. Deserialization Vulnerabilities

**Requirements**:

- [ ] Never use `pickle` with untrusted data
- [ ] Use `json` for data serialization
- [ ] Validate deserialized object types

**Examples**:

```python
# ❌ DANGEROUS - Pickle with user data
import pickle
data = pickle.loads(user_provided_data)  # Code execution!

# ✅ SAFE - JSON instead
import json
data = json.loads(user_provided_data)

# ✅ SAFE - Type validation after deserialization
from pydantic import BaseModel

class UserData(BaseModel):
    name: str
    age: int

data = UserData(**json.loads(user_input))
```

### 10. Dependency Security

**Automated Checks**:

- [ ] `pip-audit` - OSV database vulnerability scan
- [ ] `safety` - Safety DB vulnerability scan
- [ ] Both should be in pre-commit hooks

**Manual Review**:

- [ ] Dependencies are actively maintained
- [ ] Known vulnerabilities patched
- [ ] Minimal dependencies (reduce attack surface)

**PyEye - Analyze Dependencies**:

- `expand("myapp.api", edge="imports")` to list a module's top-level imports — verify each
  is legitimate and needed (attack-surface check).
- `analyze_dependencies("myapp.api")` for the full dependency tree, including circular deps.

### 11. Framework-Specific Security

#### Flask Security

**Use Flask Plugin for Enhanced Analysis**:

```python
# PyEye automatically detects Flask and activates plugin

# Find all routes
find_routes()
# Check: Each route has proper authentication

# Find blueprints
find_blueprints()
# Verify: Security middleware applied

# Find error handlers
find_error_handlers()
# Check: No information leakage in errors
```

**Requirements**:

- [ ] CSRF protection enabled (Flask-WTF)
- [ ] Secure session cookies (`SESSION_COOKIE_SECURE=True`)
- [ ] Input validation on all routes
- [ ] Authentication on protected endpoints

#### Django Security

**Use Django Plugin**:

```python
# Find all views
find_django_views()
# Check: Permission decorators present

# Find models
find_django_models()
# Verify: Sensitive fields encrypted
```

**Requirements**:

- [ ] CSRF middleware enabled
- [ ] SQL injection protection (ORM)
- [ ] XSS protection (template auto-escaping)
- [ ] Secure settings (`DEBUG=False` in production)

## Security Review Workflow

### Step 1: Automated Scanning

Run security tools:

```bash
# Dependency vulnerabilities
pip-audit
safety check

# Code security scanning
bandit -r src/
ruff check --select S

# Secret detection
detect-secrets scan
```

### Step 2: Input Validation Review

For each user input point:

1. `resolve` the input handler to a handle
2. `expand(edge="callees")` / `trace(follow=["callees"])` - follow data forward
3. Verify validation exists before use
4. Check for injection vulnerabilities

### Step 3: Authentication/Authorization Review

1. `resolve` auth entry points (`authenticate`, `login`)
2. Enumerate protected entry points (e.g. `find_routes()` for Flask) and `Read` each handler
3. `expand(edge="callees")` - confirm auth code reaches a verify/hash routine
4. Verify authorization on each protected resource (reverse "is it checked everywhere?"
   can't be statically confirmed — #333)

### Step 4: Data Flow Analysis

For sensitive data:

1. Identify data entry points
2. `trace(follow=["callees"])` - follow forward toward sinks
3. Verify encryption/hashing applied
4. Check logs don't leak data — note that complete reverse taint flow is unconfirmable (#333)

### Step 5: Framework-Specific Review

If Flask/Django detected:

1. Use framework plugin tools
2. Check framework-specific security settings
3. Verify security middleware configured

## Complete Security Review Example

**Scenario**: Reviewing user authentication API endpoint

### Automated Scanning

```bash
✅ pip-audit - no vulnerabilities
✅ safety check - passed
✅ bandit - 2 issues found (B608: hardcoded SQL, B105: password check)
✅ detect-secrets - 1 potential secret found
```

### PyEye-Enhanced Analysis

```text
# 1. Resolve the login endpoint to a handle
resolve("login")
→ handle: api.auth.login  (api/auth.py:45)

# 2. Inspect implementation
inspect("api.auth.login")
→ signature: login(username: str, password: str)
→ has SQL query - needs review ⚠️

# 3. Follow data forward (reliable)
expand("api.auth.login", edge="callees")
→ calls: validate_credentials, create_session
→ NOTE: "who calls login?" (callers) is deferred (#333) — not shown

# 4. Check password handling
# Reverse "where is password referenced?" is not available (#333).
# Read api/auth.py around line 45 to confirm:
→ Used in bcrypt.checkpw() ✅  /  never logged ✅  /  not stored ✅

# 5. Check SQL usage
# Bandit flagged: "SELECT * FROM users WHERE username = ?"
→ Uses parameterized query ✅  /  no string concatenation ✅
```

### Manual Review Findings

- ⚠️ Bandit B608 false positive - parameterized query used correctly
- ✅ Password hashed with bcrypt
- ✅ Session tokens use secrets.token_urlsafe()
- ✅ Input validation on username
- ✅ Rate limiting on login endpoint
- ⚠️ Detect-secrets found test API key in test file - add to .secrets.baseline

**Result**: APPROVED with minor fix (add test key to baseline)

## Critical Security Checklist

**Must Review**:

- [ ] All user input validated
- [ ] No SQL/command injection possible
- [ ] Passwords properly hashed (bcrypt/argon2)
- [ ] No secrets in code
- [ ] Dependencies scanned for vulnerabilities
- [ ] Authorization checked on protected resources
- [ ] Sensitive data encrypted
- [ ] Error messages don't leak information

**PyEye Tools Used**:

- [ ] `expand(edge="callees")` / `trace` - Followed data flow forward
- [ ] `expand(edge="imports"|"imported_by")` - Checked import surface
- [ ] `analyze_dependencies()` - Checked dependency tree
- [ ] Framework plugins - Framework-specific checks
- [ ] Acknowledged reverse-reference limit (#333) where taint flow couldn't be confirmed

## Success Indicators

✅ **Automated scans pass** - No vulnerabilities detected by tools
✅ **Data flow traced** - Know where sensitive data goes
✅ **Input validated** - All entry points checked
✅ **Auth verified** - Authorization on all protected resources
✅ **Secrets safe** - No hardcoded credentials
✅ **Framework secure** - Framework-specific protections enabled

## Common Security Mistakes

1. **Trusting client-side validation only**
2. **Using weak/deprecated crypto (MD5, SHA1 for passwords)**
3. **Not checking authorization on every request**
4. **Logging sensitive data**
5. **Hardcoding secrets**
6. **Using `shell=True` with user input**
7. **Not validating file uploads**
8. **Deserializing untrusted data with pickle**

## Related Workflows

- [Code Review Standards](workflows://code-review-standards) - General Python best practices
- [PR Review](workflows://code-review-pr) - Complete pull request review
- [Code Understanding](workflows://code-understanding) - Understand security-critical code

## Security Resources

**OWASP**:

- [OWASP Code Review Guide](https://owasp.org/www-project-code-review-guide/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [OWASP Secure Coding Practices](https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/)

**Python Security**:

- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [Bandit Security Linter](https://bandit.readthedocs.io/)
- [OWASP Python Security](https://cheatsheetseries.owasp.org/cheatsheets/Python_Security_Cheat_Sheet.html)

**Tools**:

- `bandit` - Python security linter
- `pip-audit` - Dependency vulnerability scanner
- `safety` - Dependency checker
- `detect-secrets` - Secret detection
- `semgrep` - Advanced static analysis
