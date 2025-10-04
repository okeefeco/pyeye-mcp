# Python Security Code Review (OWASP 2025)

## Goal

Identify security vulnerabilities in Python code using OWASP guidelines and PyEye's semantic analysis to trace data flow, validate input handling, and detect security anti-patterns.

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

## OWASP Security Checklist

### 1. Input Validation

**Critical**: All external input must be validated

**Review Points**:

- [ ] All user input is validated before use
- [ ] Whitelist validation preferred over blacklist
- [ ] Input length and type constraints enforced
- [ ] Special characters properly handled
- [ ] File uploads validated (type, size, content)

**MCP Tool - Trace Input Flow**:

```python
# Find where user input enters the system
find_symbol(name="request_handler", fuzzy=True)

# Trace how input flows through the code
get_call_hierarchy(function_name="process_user_input")
# Returns: callers (where input comes from) and callees (where it goes)

# Find all places that handle user input
find_references(file=handler_file, line=input_line)
# Verify: Each reference validates input
```

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

```python
# Search for SQL injection patterns
find_symbol(name="execute", fuzzy=True)
# Look for database execute calls

get_call_hierarchy(function_name="execute")
# Trace back to see if SQL is constructed from user input
```

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

**MCP Tool - Find Command Execution**:

```python
# Find all subprocess usage
find_imports(module_name="subprocess")

# Check each usage
get_type_info(file=subprocess_file, line=subprocess_line, detailed=True)
# Verify: shell=False, list arguments used
```

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

**MCP Tool - Find File Operations**:

```python
# Find file operations
find_symbol(name="open", fuzzy=True)
find_symbol(name="Path", fuzzy=True)

# Trace where file paths come from
get_call_hierarchy(function_name="read_file")
# Verify: Path validation exists
```

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

**MCP Tool - Find Auth Patterns**:

```python
# Find authentication functions
find_symbol(name="authenticate", fuzzy=True)
find_symbol(name="login", fuzzy=True)

# Check password handling
find_references(file=auth_file, line=password_line)
# Verify: Hashing used, no plaintext storage

# For Flask apps - use Flask plugin
# (Automatically detects Flask and provides specialized tools)
find_routes()  # Lists all routes
# Check: Each protected route has auth decorator
```

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

**MCP Tool - Find Hardcoded Secrets**:

```python
# Find string constants that might be secrets
find_symbol(name="API_KEY", fuzzy=True)  # pragma: allowlist secret
find_symbol(name="SECRET", fuzzy=True)  # pragma: allowlist secret
find_symbol(name="PASSWORD", fuzzy=True)  # pragma: allowlist secret

# Check if loaded from environment
get_type_info(...)
# Verify: Uses os.environ or config system
```

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

**MCP Tool - Analyze Dependencies**:

```python
# Check what the module imports
get_module_info(module_path="myapp.api")
# Returns: imports list

# Verify each import is legitimate and needed
analyze_dependencies(module_path="myapp.api")
# Returns: Full dependency tree
```

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

1. `find_symbol()` - Locate input handlers
2. `get_call_hierarchy()` - Trace data flow
3. Verify validation exists before use
4. Check for injection vulnerabilities

### Step 3: Authentication/Authorization Review

1. `find_symbol(name="auth", fuzzy=True)` - Find auth code
2. `find_references()` - See where auth is checked
3. `get_call_hierarchy()` - Trace auth flow
4. Verify authorization on all protected resources

### Step 4: Data Flow Analysis

For sensitive data:

1. Identify data entry points
2. `get_call_hierarchy()` - Trace where data goes
3. Verify encryption/hashing applied
4. Check logs don't leak data

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

### MCP-Enhanced Analysis

```python
# 1. Find the login endpoint
find_symbol(name="login")
→ Found at: api/auth.py:45

# 2. Check implementation
get_type_info(file="api/auth.py", line=45, detailed=True)
→ Function: login(username: str, password: str)
→ Has SQL query - needs review ⚠️

# 3. Trace data flow
get_call_hierarchy(function_name="login")
→ Calls: validate_credentials, create_session
→ Called by: api_endpoint

# 4. Check password handling
find_references(file="api/auth.py", line=password_line)
→ Used in: bcrypt.checkpw() ✅
→ Never logged ✅
→ Not stored ✅

# 5. Check SQL usage
# Bandit flagged: "SELECT * FROM users WHERE username = ?"
→ Uses parameterized query ✅
→ No string concatenation ✅
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

**MCP Tools Used**:

- [ ] `get_call_hierarchy()` - Traced data flow
- [ ] `find_references()` - Found all usages
- [ ] `analyze_dependencies()` - Checked imports
- [ ] Framework plugins - Framework-specific checks

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
