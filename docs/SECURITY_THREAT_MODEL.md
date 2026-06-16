# TempleDB Security Threat Model

**Version:** 1.0
**Last Updated:** 2026-03-03
**Status:** Draft

---

## Executive Summary

TempleDB is a **single-user, local-first** database-native project management system. This threat model identifies potential security risks, attack vectors, and mitigations for the current architecture.

**Key Finding:** TempleDB's current single-user, local-only design significantly limits the attack surface compared to networked multi-user systems. However, several critical risks exist around **data integrity, secrets management, and malicious input handling**.

---

## System Overview

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      User's Machine                      │
│                                                          │
│  ┌──────────────┐         ┌─────────────────┐          │
│  │TempleDB CLI  │────────▶│  SQLite Database│          │
│  │   (Python)   │◀────────│  (templedb.db)  │          │
│  └──────────────┘         └─────────────────┘          │
│         │                           │                   │
│         │                           │                   │
│  ┌──────▼──────┐           ┌───────▼────────┐          │
│  │  Filesystem │           │  Age Keys      │          │
│  │  (Projects) │           │  (~/.age/)     │          │
│  └─────────────┘           └────────────────┘          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Trust Boundaries

1. **User ↔ TempleDB**: User fully trusts TempleDB (single-user assumption)
2. **TempleDB ↔ Filesystem**: Trust files read from disk (could be malicious)
3. **TempleDB ↔ SQLite DB**: Trust database integrity (could be corrupted)
4. **TempleDB ↔ Age Keys**: Trust key material (could be stolen)
5. **TempleDB ↔ External Tools**: Limited trust (git, age, editors)
6. **TempleDB ↔ Cathedral Packages**: **DO NOT TRUST** - external, untrusted source

---

## Threat Actors

### Primary Threat Actors

1. **Malicious Local User**
   - Has shell access to the same machine
   - Can read/write files
   - Can run TempleDB commands
   - Goal: Steal data, corrupt database, escalate privileges

2. **Malicious Cathedral Package Author**
   - Creates poisoned Cathedral packages
   - Goal: Inject malicious files, backdoors, or data

3. **Malware on User's Machine**
   - Ransomware, spyware, trojans
   - Goal: Encrypt/steal data, exfiltrate secrets

4. **Supply Chain Attacker**
   - Compromises Python dependencies
   - Goal: Inject malicious code into TempleDB

5. **Insider Threat (Future: Multi-User)**
   - Authorized user with malicious intent
   - Goal: Data theft, sabotage, privilege escalation

### Secondary Threat Actors

6. **Physical Attacker**
   - Has physical access to machine
   - Goal: Steal disk, extract data

7. **Network Attacker (Future: Remote Features)**
   - Man-in-the-middle, eavesdropping
   - Goal: Intercept data, steal credentials

---

## Threat Categories & Attack Scenarios

---

## 🔴 CRITICAL THREATS

### T1: SQL Injection

**Category:** Code Injection
**Likelihood:** Medium
**Impact:** Critical
**Current Status:** ⚠️ Partially Mitigated

**Attack Scenario:**
```python
# Vulnerable code (example)
user_input = args.project_name
query = f"SELECT * FROM projects WHERE name = '{user_input}'"
db.execute(query)  # DANGER!

# Attacker provides:
# --project-name "'; DROP TABLE projects; --"
```

**Exploitation:**
- Attacker provides malicious input to CLI arguments
- Input not properly sanitized
- SQL executed with malicious payload
- Database corrupted or data exfiltrated

**Impact:**
- **Data loss** - DROP TABLE, DELETE operations
- **Data theft** - Extract all database contents
- **Privilege escalation** - Bypass access controls (future multi-user)
- **Code execution** - Via SQLite extensions or ATTACH DATABASE

**Current Mitigations:** ✅
- Parameterized queries used throughout codebase
- SQLite parameter binding with `?` placeholders

**Remaining Risks:** ⚠️
- Dynamic query construction in some places
- Raw SQL in migration files (controlled, but verify)
- User-provided SQL in `templedb query` command

**Recommendations:**
- [ ] Audit all database queries for SQL injection
- [ ] Automated testing with SQLMap or similar
- [ ] Strict input validation on all user inputs
- [ ] Disable dangerous SQLite features:
  ```python
  db.execute("PRAGMA trusted_schema = OFF")
  ```

---

### T2: Path Traversal / Directory Traversal

**Category:** File System Attack
**Likelihood:** High
**Impact:** Critical
**Current Status:** ⚠️ Partially Mitigated

**Attack Scenario:**
```bash
# Attacker tries to escape project directory
templedb project import /tmp/malicious-project

# malicious-project contains:
#   ../../../../etc/passwd -> symlink
#   ../../../.ssh/id_rsa -> symlink
```

**Exploitation:**
- Attacker creates project with path traversal (`../../../etc/passwd`)
- TempleDB imports file outside project boundary
- Attacker reads sensitive files
- Or overwrites system files on checkout/export

**Impact:**
- **Read arbitrary files** - `/etc/passwd`, SSH keys, secrets
- **Write arbitrary files** - Overwrite system files, plant backdoors
- **Code execution** - Overwrite `.bashrc`, cron jobs

**Current Mitigations:** ✅
- CWD-based discovery with `.templedb/` marker
- Relative path storage in database
- `Path.resolve()` used in many places

**Remaining Risks:** ⚠️
- Symlink handling unclear
- No validation that files are within project root
- Cathedral imports could contain malicious paths
- Checkout could write outside target directory

**Recommendations:**
- [ ] **Strict path validation:**
  ```python
  def validate_path(project_root: Path, file_path: Path) -> bool:
      resolved = file_path.resolve()
      return resolved.is_relative_to(project_root)
  ```
- [ ] **Reject symlinks** or follow them carefully
- [ ] **Validate all file paths** before read/write
- [ ] **Sandbox Cathedral imports** - extract to temp, validate, then import
- [ ] **Test with malicious paths:**
  - `../../../etc/passwd`
  - `../../../../root/.ssh/id_rsa`
  - Absolute paths: `/etc/passwd`
  - Symlinks to sensitive files

---

### T3: Age Key Theft / Exposure

**Category:** Secrets Management
**Likelihood:** Medium
**Impact:** Critical
**Current Status:** 🔴 Vulnerable

**Attack Scenario:**
```bash
# Keys stored in plaintext
~/.config/sops/age/keys.txt
~/.age/key.txt

# Attacker gains read access:
cat ~/.config/sops/age/keys.txt
# AGE-SECRET-KEY-1... (private key exposed!)

# Now attacker can decrypt all secrets
```

**Exploitation:**
- Age private keys stored unencrypted on disk
- Malware reads key file
- Attacker decrypts all secrets in database
- Attacker can impersonate user (future multi-user)

**Impact:**
- **Secret exposure** - All encrypted secrets compromised
- **Long-term compromise** - Historical data exposed
- **Lateral movement** - Secrets may grant access to other systems
- **Non-repudiation loss** - Attacker can forge signatures

**Current Mitigations:** ❌ None
- Keys stored in plaintext
- No key encryption at rest
- No hardware security module (HSM) support

**Recommendations:**
- [ ] **Encrypt keys at rest** with OS keychain:
  - macOS: Keychain Access
  - Linux: gnome-keyring, KWallet, or pass
  - Windows: Credential Manager
- [ ] **Support hardware tokens:**
  - YubiKey (age-plugin-yubikey)
  - TPM 2.0
  - FIDO2 keys
- [ ] **Key rotation:**
  - Periodic re-encryption with new keys
  - Revocation support
- [ ] **Secure key generation:**
  ```bash
  # Generate with strict permissions
  (umask 0077 && age-keygen -o ~/.age/key.txt)
  ```
- [ ] **Warn on insecure permissions:**
  ```python
  key_file = Path("~/.age/key.txt").expanduser()
  if key_file.stat().st_mode & 0o077:
      print("WARNING: Key file has insecure permissions!")
  ```

---

### T4: Database Corruption / Tampering

**Category:** Data Integrity
**Likelihood:** Medium
**Impact:** Critical
**Current Status:** 🔴 No Detection

**Attack Scenario:**
```bash
# Attacker directly modifies database
sqlite3 ~/.local/share/templedb/templedb.db
> UPDATE projects SET repo_url = '/attacker/malicious';
> DELETE FROM file_contents WHERE id < 1000;

# Or filesystem corruption
# Power loss during write
# Disk failure
# Ransomware partial encryption
```

**Exploitation:**
- Attacker has write access to database file
- Manually edits with sqlite3 CLI
- Corrupts data, injects malicious records
- Or natural corruption (disk failure, power loss)

**Impact:**
- **Data loss** - Silent corruption undetected
- **Code execution** - Malicious file paths injected
- **Backdoors** - Inject malicious code into projects
- **Undetected compromise** - No integrity validation

**Current Mitigations:** ❌ None
- No checksums on database
- No integrity validation
- No tamper detection
- SQLite integrity checks not automated

**Recommendations:**
- [ ] **Implement integrity checks:**
  ```bash
  templedb integrity check
  templedb integrity check --deep
  templedb integrity repair
  ```
- [ ] **Content-addressable storage:**
  - Hash all file contents
  - Store hash alongside content
  - Verify on read
- [ ] **Database checksums:**
  ```sql
  CREATE TABLE integrity_checksums (
      table_name TEXT PRIMARY KEY,
      checksum TEXT,
      last_verified TIMESTAMP
  );
  ```
- [ ] **SQLite integrity:**
  ```python
  db.execute("PRAGMA integrity_check")
  db.execute("PRAGMA foreign_key_check")
  ```
- [ ] **Write-ahead logging (WAL):**
  ```python
  db.execute("PRAGMA journal_mode = WAL")
  ```
- [ ] **Automatic verification:**
  - On startup: Quick integrity check
  - Periodic: Full verification
  - Before critical operations: Validation

---

### T5: Malicious Cathedral Package Import

**Category:** Supply Chain Attack
**Likelihood:** Medium (as adoption grows)
**Impact:** Critical
**Current Status:** 🔴 No Validation

**Attack Scenario:**
```bash
# Attacker creates malicious Cathedral package
malicious.cathedral.tar.gz

# Contains:
#   .templedb/config     # Valid metadata
#   README.md            # Looks innocent
#   .git/hooks/post-checkout  # MALICIOUS!
#   src/backdoor.sh      # Malicious payload
#   ../../../../.bashrc  # Path traversal

# Victim imports:
templedb cathedral import malicious.cathedral.tar.gz

# Malicious code now on system
```

**Exploitation:**
- Attacker distributes poisoned Cathedral package
- Victim imports package trusting it's safe
- Malicious files extracted to filesystem
- Code execution on next git operation, shell start, etc.

**Impact:**
- **Code execution** - Arbitrary code on victim's machine
- **Backdoor installation** - Persistent access
- **Data exfiltration** - Steal source code, secrets
- **Supply chain compromise** - Poison trusted projects

**Current Mitigations:** ❌ None
- No package signing
- No signature verification
- No integrity checks
- Trust on first use (TOFU) only

**Recommendations:**
- [ ] **Package signing (GPG or Sigstore):**
  ```bash
  # Export with signature
  templedb cathedral export myproject --sign

  # Import with verification
  templedb cathedral import package.tar.gz --verify
  ```
- [ ] **Checksum publication:**
  ```bash
  # Publish checksums separately
  sha256sum package.tar.gz > package.tar.gz.sha256

  # Verify before import
  templedb cathedral import package.tar.gz --checksum package.tar.gz.sha256
  ```
- [ ] **Sandboxed extraction:**
  - Extract to temporary directory first
  - Validate all paths
  - Scan for malicious files
  - User approval before final import
- [ ] **Malware scanning:**
  - Scan for known patterns (git hooks, shell scripts)
  - Reject dangerous file types
  - Warn on executable files
- [ ] **Trust model:**
  - Trusted package registry
  - Web of trust (PGP-style)
  - Certificate pinning
- [ ] **Audit trail:**
  ```sql
  CREATE TABLE cathedral_imports (
      id INTEGER PRIMARY KEY,
      package_name TEXT,
      checksum TEXT,
      signature TEXT,
      imported_by TEXT,
      imported_at TIMESTAMP,
      verification_status TEXT  -- 'verified', 'unverified', 'failed'
  );
  ```

---

## 🟠 HIGH THREATS

### T6: Command Injection

**Category:** Code Injection
**Likelihood:** Low
**Impact:** Critical
**Current Status:** ⚠️ Partially Mitigated

**Attack Scenario:**
```python
# Vulnerable code (example)
project_name = args.name
os.system(f"git clone {repo_url} {project_name}")  # DANGER!

# Attacker provides:
# --name "project; rm -rf /"
```

**Exploitation:**
- User input passed to shell commands
- Not properly escaped
- Shell interprets special characters
- Arbitrary command execution

**Impact:**
- **Code execution** - Run arbitrary commands
- **Data loss** - Delete files
- **System compromise** - Install malware

**Current Mitigations:** ✅ Mostly
- `subprocess.run()` used with list args (safe)
- Avoid `os.system()` and `shell=True`

**Remaining Risks:** ⚠️
- External tool invocations (git, age, editors)
- Environment variable injection (EDITOR, PAGER)
- Unsanitized user input to subprocess

**Recommendations:**
- [ ] **Never use `shell=True`** unless absolutely necessary
- [ ] **Use list arguments:**
  ```python
  # Safe
  subprocess.run(["git", "clone", repo_url, project_name])

  # UNSAFE
  subprocess.run(f"git clone {repo_url} {project_name}", shell=True)
  ```
- [ ] **Validate environment variables:**
  ```python
  editor = os.environ.get("EDITOR", "vi")
  if not is_safe_editor(editor):
      raise ValueError("Unsafe EDITOR")
  ```
- [ ] **Whitelist allowed characters** in inputs
- [ ] **Audit all subprocess calls**

---

### T7: Secrets Leakage in Logs/Errors

**Category:** Information Disclosure
**Likelihood:** Medium
**Impact:** High
**Current Status:** ⚠️ Unknown

**Attack Scenario:**
```python
# Accidentally log secret
logger.debug(f"Decrypting secret: {plaintext_secret}")

# Logs written to:
# ~/.local/share/templedb/logs/templedb.log

# Attacker reads log file
cat ~/.local/share/templedb/logs/templedb.log
# Decrypting secret: AWS_SECRET_KEY=abc123...
```

**Exploitation:**
- Secrets logged in plaintext
- Error messages contain sensitive data
- Stack traces reveal internal state
- Logs not properly secured

**Impact:**
- **Secret exposure** - Credentials leaked
- **Lateral movement** - Secrets grant access elsewhere
- **Compliance violation** - GDPR, PCI-DSS

**Current Mitigations:** ⚠️ Unknown
- Logging implementation unclear
- No secret redaction

**Recommendations:**
- [ ] **Never log secrets:**
  ```python
  # BAD
  logger.debug(f"Secret: {secret}")

  # GOOD
  logger.debug(f"Secret: {'*' * 8}")
  ```
- [ ] **Redact sensitive data:**
  ```python
  def redact(s: str) -> str:
      if len(s) < 8:
          return "***"
      return s[:4] + "..." + s[-4:]

  logger.debug(f"API key: {redact(api_key)}")
  ```
- [ ] **Secure log permissions:**
  ```bash
  chmod 600 ~/.local/share/templedb/logs/*.log
  ```
- [ ] **Log rotation and cleanup:**
  - Rotate logs regularly
  - Secure deletion of old logs
- [ ] **Audit all logging statements** for secrets

---

### T8: Insecure Temporary Files

**Category:** Information Disclosure
**Likelihood:** Medium
**Impact:** High
**Current Status:** ⚠️ Unknown

**Attack Scenario:**
```python
# Create temp file for editing secrets
with open("/tmp/secrets.yaml", "w") as f:
    f.write(decrypted_secrets)

# Invoke editor
os.system(f"$EDITOR /tmp/secrets.yaml")

# Temp file left on disk with secrets!
# Attacker finds:
ls /tmp/secrets*
cat /tmp/secrets.yaml
```

**Exploitation:**
- Temporary files created with predictable names
- World-readable permissions
- Not securely deleted after use
- Attacker reads temp files

**Impact:**
- **Secret exposure** - Temporary files contain plaintext
- **Residual data** - Data persists after deletion
- **Forensic recovery** - Deleted files recoverable

**Current Mitigations:** ⚠️ Unknown
- `tempfile.NamedTemporaryFile` usage unclear
- Secure deletion not implemented

**Recommendations:**
- [ ] **Use secure temporary files:**
  ```python
  with tempfile.NamedTemporaryFile(
      mode='w',
      suffix='.yaml',
      delete=True,  # Auto-delete
      dir=secure_tmp_dir(),
  ) as f:
      f.write(secret_data)
  ```
- [ ] **Restrict permissions:**
  ```python
  os.chmod(temp_file, 0o600)  # User read/write only
  ```
- [ ] **Secure deletion:**
  ```python
  # Overwrite before delete (defense in depth)
  with open(temp_file, 'wb') as f:
      f.write(os.urandom(os.path.getsize(temp_file)))
  os.unlink(temp_file)
  ```
- [ ] **Use memory-backed tmpfs:**
  ```python
  # Linux
  temp_dir = "/dev/shm"  # RAM-backed, not written to disk
  ```
- [ ] **Clean up on exit:**
  ```python
  import atexit
  atexit.register(cleanup_temp_files)
  ```

---

### T9: Denial of Service (Resource Exhaustion)

**Category:** Availability
**Likelihood:** Low
**Impact:** Medium
**Current Status:** 🔴 No Limits

**Attack Scenario:**
```bash
# Create massive project
for i in $(seq 1 1000000); do
    echo "file $i" > "file_$i.txt"
done

# Import into TempleDB
templedb project import /path/to/huge-project

# TempleDB crashes:
# - Out of memory
# - Out of disk space
# - Database locked indefinitely
```

**Exploitation:**
- Attacker creates project with:
  - Millions of files
  - Multi-GB files
  - Deep directory nesting (10,000 levels)
  - Circular symlinks
- TempleDB attempts to import
- Resource exhaustion (memory, disk, CPU)
- System becomes unresponsive

**Impact:**
- **Service disruption** - TempleDB crashes
- **Data loss** - Incomplete writes
- **System instability** - Machine unresponsive

**Current Mitigations:** ❌ None
- No resource limits
- No rate limiting
- No size validation

**Recommendations:**
- [ ] **Enforce limits:**
  ```python
  MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024  # 1GB
  MAX_FILE_COUNT = 1_000_000
  MAX_PATH_DEPTH = 100
  MAX_DISK_USAGE = 100 * 1024 * 1024 * 1024  # 100GB
  ```
- [ ] **Validate before import:**
  ```python
  def validate_project(path: Path):
      file_count = sum(1 for _ in path.rglob("*"))
      if file_count > MAX_FILE_COUNT:
          raise ValueError(f"Too many files: {file_count}")
  ```
- [ ] **Stream processing:**
  - Don't load entire files into memory
  - Process incrementally
  - Chunk large files
- [ ] **Timeout operations:**
  ```python
  import signal
  signal.alarm(3600)  # 1 hour max
  ```
- [ ] **Disk space checks:**
  ```python
  import shutil
  free_space = shutil.disk_usage("/").free
  if free_space < MIN_FREE_SPACE:
      raise IOError("Insufficient disk space")
  ```

---

### T10: Unauthorized Database Access (Multi-User Future)

**Category:** Access Control
**Likelihood:** N/A (single-user currently)
**Impact:** Critical (multi-user future)
**Current Status:** 🔴 No Access Control

**Attack Scenario:**
```bash
# Single-user: anyone with disk access has full access
sqlite3 ~/.local/share/templedb/templedb.db
> SELECT * FROM secret_blobs;  # All secrets!

# Multi-user future: same risk if not addressed
```

**Exploitation:**
- No authentication required
- No authorization checks
- Any process can open database
- Any user on system has full access

**Impact:**
- **Data theft** - Read all projects, commits, secrets
- **Data tampering** - Modify records
- **Privilege escalation** - Grant self admin rights

**Current Mitigations:** ✅ By design (single-user)
- Assumes single trusted user
- OS-level file permissions only protection

**Future Mitigations (Multi-User):**
- [ ] **Move to PostgreSQL with RLS (Row-Level Security)**
- [ ] **Authentication layer** (JWT, sessions)
- [ ] **Authorization checks** on all queries
- [ ] **Audit all database access**
- [ ] **Encrypt database at rest**

---

## 🟡 MEDIUM THREATS

### T11: Dependency Vulnerabilities

**Category:** Supply Chain
**Likelihood:** Medium
**Impact:** Variable
**Current Status:** ⚠️ No Monitoring

**Attack Scenario:**
```bash
# TempleDB depends on vulnerable package
pip install templedb

# Installs PyYAML 5.3 (has CVE-2020-1747)
# Arbitrary code execution via malicious YAML
```

**Recommendations:**
- [ ] **Dependency pinning** (requirements.txt)
- [ ] **Automated vulnerability scanning** (Snyk, Dependabot)
- [ ] **SBOM generation** (Software Bill of Materials)
- [ ] **Regular updates**

---

### T12: Code Execution via File Type Handlers

**Category:** Code Injection
**Likelihood:** Low
**Impact:** High
**Current Status:** ⚠️ Unknown

**Attack Scenario:**
```python
# TempleDB parses SQL file
with open("malicious.sql") as f:
    content = f.read()
    # If parser has vulnerabilities...
    parse_sql(content)  # Code execution!
```

**Recommendations:**
- [ ] **Sandboxed parsing**
- [ ] **Untrusted input handling**
- [ ] **Parser fuzzing**

---

### T13: Race Conditions (TOCTOU)

**Category:** Time-of-Check to Time-of-Use
**Likelihood:** Low
**Impact:** Medium
**Current Status:** ⚠️ Possible

**Attack Scenario:**
```python
# Check file permissions
if os.access(file_path, os.R_OK):
    # Attacker changes file here (symlink swap)
    with open(file_path) as f:  # Now reading different file!
        data = f.read()
```

**Recommendations:**
- [ ] **Use file descriptors** instead of paths
- [ ] **Atomic operations** where possible
- [ ] **Proper locking**

---

### T14: Information Disclosure via Error Messages

**Category:** Information Disclosure
**Likelihood:** Medium
**Impact:** Low
**Current Status:** ⚠️ Unknown

**Attack Scenario:**
```bash
templedb project show "'; OR 1=1--"

# Error reveals internal query:
# Error: near "'; OR 1=1--": syntax error in:
# SELECT * FROM projects WHERE slug = ''; OR 1=1--'
```

**Recommendations:**
- [ ] **Generic error messages** to users
- [ ] **Detailed errors in logs** only
- [ ] **No stack traces** in production

---

### T15: Unvalidated Redirects (Future Web UI)

**Category:** Phishing
**Likelihood:** N/A (no web UI)
**Impact:** Medium
**Current Status:** N/A

**For future web UI:**
- [ ] **Validate all redirect URLs**
- [ ] **Whitelist allowed domains**
- [ ] **No user-controlled redirects**

---

## 🔵 LOW THREATS

### T16: Side-Channel Attacks

**Category:** Cryptographic
**Likelihood:** Very Low
**Impact:** Low
**Current Status:** Out of scope

**Examples:**
- Timing attacks on password comparison
- Cache timing attacks
- Power analysis

**Recommendation:** Accept risk (out of scope for CLI tool)

---

### T17: Social Engineering

**Category:** Human
**Likelihood:** Medium (general threat)
**Impact:** Variable
**Current Status:** User awareness

**Examples:**
- Phishing for Age keys
- Fake Cathedral packages
- Malicious documentation links

**Recommendations:**
- [ ] **User education** in documentation
- [ ] **Warning messages** for dangerous operations
- [ ] **Verify package sources**

---

## Mitigations Summary

### Implemented ✅
1. Parameterized SQL queries (prevents SQL injection)
2. Relative path storage (helps prevent path traversal)
3. `subprocess.run()` with list args (prevents command injection)

### Partially Implemented ⚠️
1. Path validation (needs comprehensive audit)
2. Input sanitization (inconsistent)
3. Error handling (reveals too much?)

### Not Implemented 🔴
1. **Database integrity checks** ← CRITICAL
2. **Cathedral package signing** ← CRITICAL
3. **Age key encryption at rest** ← CRITICAL
4. **Resource limits** ← HIGH
5. **Secret redaction in logs** ← HIGH
6. **Temporary file security** ← MEDIUM
7. **Dependency vulnerability scanning** ← MEDIUM

---

## Security Checklist

### Before 1.0 Release

- [ ] **SQL Injection Audit**
  - Review all database queries
  - Test with SQLMap
  - Automated regression tests

- [ ] **Path Traversal Audit**
  - Validate all file paths
  - Reject symlinks or handle safely
  - Test with malicious paths

- [ ] **Integrity Framework**
  - Implement `templedb integrity check`
  - Content-addressable storage
  - Database checksums

- [ ] **Cathedral Security**
  - Package signing (GPG or Sigstore)
  - Signature verification
  - Sandboxed extraction

- [ ] **Secrets Management**
  - Encrypt Age keys at rest
  - OS keychain integration
  - Secure temp file handling

- [ ] **Resource Limits**
  - Max file size
  - Max file count
  - Disk space checks

- [ ] **Security Documentation**
  - Responsible disclosure policy (SECURITY.md)
  - Security best practices
  - Threat model (this document)

### Ongoing

- [ ] **Dependency Scanning**
  - Automated tools (Dependabot)
  - Regular updates
  - CVE monitoring

- [ ] **Security Audits**
  - Annual penetration testing
  - Code review
  - Third-party audit

- [ ] **Incident Response Plan**
  - Disclosure timeline
  - Patch process
  - Communication plan

---

## Responsible Disclosure

**How to report security vulnerabilities:**

1. **DO NOT** open a public GitHub issue
2. Email: security@templedb.dev (or maintainer email)
3. Use GPG key: [KEY_ID] for encrypted communication
4. Include:
   - Description of vulnerability
   - Steps to reproduce
   - Proof of concept (if applicable)
   - Suggested fix (optional)

**Response timeline:**
- Acknowledgment: Within 48 hours
- Initial assessment: Within 1 week
- Fix development: Within 30 days (critical) or 90 days (others)
- Disclosure: Coordinated with reporter

---

## Risk Matrix

| Threat | Likelihood | Impact | Risk Level | Priority |
|--------|-----------|--------|------------|----------|
| T1: SQL Injection | Medium | Critical | 🔴 HIGH | P1 |
| T2: Path Traversal | High | Critical | 🔴 CRITICAL | P0 |
| T3: Age Key Theft | Medium | Critical | 🔴 HIGH | P1 |
| T4: DB Corruption | Medium | Critical | 🔴 HIGH | P0 |
| T5: Malicious Cathedral | Medium | Critical | 🔴 HIGH | P1 |
| T6: Command Injection | Low | Critical | 🟠 MEDIUM | P2 |
| T7: Secrets in Logs | Medium | High | 🟠 MEDIUM | P2 |
| T8: Insecure Temp Files | Medium | High | 🟠 MEDIUM | P2 |
| T9: DoS (Resource) | Low | Medium | 🟡 LOW | P3 |
| T10: Unauthorized Access | N/A | Critical | ⚪ FUTURE | - |
| T11: Dependency Vulns | Medium | Variable | 🟡 LOW | P3 |
| T12: Parser Exploits | Low | High | 🟡 LOW | P3 |
| T13: Race Conditions | Low | Medium | 🟡 LOW | P4 |
| T14: Info Disclosure | Medium | Low | 🟡 LOW | P4 |

**Priority:**
- **P0:** Fix before any release
- **P1:** Fix before 1.0 stable
- **P2:** Fix in 1.x series
- **P3:** Nice to have
- **P4:** Accept risk

---

## Conclusion

TempleDB's **single-user, local-first** design significantly reduces attack surface compared to networked systems. However, several critical security risks exist:

**Immediate priorities (P0/P1):**
1. Path traversal prevention (P0)
2. Database integrity checks (P0)
3. SQL injection audit (P1)
4. Cathedral package signing (P1)
5. Age key security improvements (P1)

**Long-term considerations:**
- Multi-user architecture requires complete security redesign
- Web UI introduces new attack vectors (XSS, CSRF, etc.)
- Network features require encryption and authentication

**Recommendation:** Address P0 and P1 items before any stable release. Security is not optional.

---

**Document Status:** Draft - needs review and validation
**Next Review:** Before 1.0 release
**Maintained by:** TempleDB Security Team


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Backup & Restore](../docs/BACKUP.md)**
- **[Error Handling Migration Guide](../docs/ERROR_HANDLING_MIGRATION.md)**
- **[Vibe Coding Quiz System](../docs/VIBE_CODING.md)**
- **[Blob Storage](../docs/BLOB_STORAGE.md)**

### Architecture

- **[Phase 2: Hierarchical Agent Dispatch - Design Document](../docs/phases/PHASE_2_DESIGN.md)**
- **[CathedralDB Design Document](../docs/advanced/CATHEDRAL.md)**

### Deployment

- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**
- **[Phase 2.3 Complete: Safe Deployment Workflow](../docs/phases/PHASE_2_3_COMPLETE.md)**

<!-- AUTO-GENERATED-INDEX:END -->
