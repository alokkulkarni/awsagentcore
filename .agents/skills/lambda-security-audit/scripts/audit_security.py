#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AWS Lambda Security Auditor — SAST for all supported Lambda runtimes.

Supported runtimes (detected by file extension):
  .py               — Python  (AST-based analysis)
  .js .mjs .cjs .ts — Node.js / TypeScript (regex-based)
  .go               — Go      (regex-based)
  .java             — Java / Spring (regex-based)

Usage:
  python3 audit_security.py <file> [<file2> ...]
  python3 audit_security.py --json <file>      # JSON output
  python3 audit_security.py --summary <file>   # Counts only

Exit codes:
  0 — no CRITICAL or HIGH issues
  1 — one or more CRITICAL/HIGH issues found
  2 — file not found or parse error

Security References:
  OWASP Top 10 2021        https://owasp.org/www-project-top-ten/
  OWASP Serverless Top 10  https://owasp.org/www-project-serverless-top-10/
  OWASP ASVS v4.0          https://owasp.org/www-project-application-security-verification-standard/
  OWASP Cheat Sheets       https://cheatsheetseries.owasp.org/
  CWE Top 25 (2023)        https://cwe.mitre.org/top25/archive/2023/2023_top25_list.html
  MITRE CVE                https://cve.mitre.org/
  NVD                      https://nvd.nist.gov/
  OSV (Open Source Vulns)  https://osv.dev/
  GitHub Advisory DB       https://github.com/advisories
  Snyk Vulnerability DB    https://security.snyk.io/
  AWS Lambda Security      https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
  AWS Secrets Manager      https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html
  PCI-DSS v4.0 Req 6.3     https://www.pcisecuritystandards.org/document_library/
  GDPR Article 32          https://gdpr-info.eu/art-32-gdpr/
"""

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# CWE → OWASP Top 10 2021 mapping
# Reference: https://owasp.org/www-project-top-ten/
CWE_TO_OWASP: Dict[str, str] = {
    "CWE-20":  "A03:2021 – Injection / Improper Input Validation",
    "CWE-78":  "A03:2021 – Injection (OS Command)",
    "CWE-89":  "A03:2021 – Injection (SQL)",
    "CWE-95":  "A03:2021 – Injection (Code)",
    "CWE-117": "A09:2021 – Security Logging and Monitoring Failures",
    "CWE-200": "A01:2021 – Broken Access Control (Sensitive Exposure)",
    "CWE-295": "A02:2021 – Cryptographic Failures (TLS Bypass)",
    "CWE-327": "A02:2021 – Cryptographic Failures (Weak Algorithm)",
    "CWE-390": "A09:2021 – Security Logging and Monitoring Failures",
    "CWE-502": "A08:2021 – Software and Data Integrity Failures",
    "CWE-532": "A09:2021 – Security Logging and Monitoring Failures",
    "CWE-611": "A05:2021 – Security Misconfiguration (XXE)",
    "CWE-798": "A02:2021 – Cryptographic Failures (Hardcoded Credentials)",
    "CWE-918": "A10:2021 – Server-Side Request Forgery (SSRF)",
}

RULES: Dict[str, Dict[str, Any]] = {
    # ── Python ────────────────────────────────────────────────────────────────
    "PY_PII_IN_LOG": {
        "severity": "CRITICAL", "language": "python", "cwe": "CWE-532",
        "message": "Full event or sensitive object serialised directly into log statement",
        "suggestion": "Use a _redact_event() helper to mask PII/financial fields before logging. See references/rules-python.md#py_pii_in_log",
        "auto_fixable": False,
    },
    "PY_HARDCODED_SECRET": {
        "severity": "CRITICAL", "language": "python", "cwe": "CWE-798",
        "message": "Possible hardcoded secret — sensitive variable name assigned a string literal",
        "suggestion": "Store secrets in AWS Secrets Manager or SSM Parameter Store. Read at runtime via boto3.",
        "auto_fixable": False,
    },
    "PY_EVAL_EXEC": {
        "severity": "CRITICAL", "language": "python", "cwe": "CWE-95",
        "message": "eval() or exec() called — code injection risk if argument contains user input",
        "suggestion": "Remove eval/exec. Use ast.literal_eval() for safe expression parsing.",
        "auto_fixable": False,
    },
    "PY_SSRF_URLOPEN": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-918",
        "message": "urllib.request.urlopen() or requests call without HTTPS scheme validation",
        "suggestion": "Validate URL scheme before calling: parsed = urlparse(url); assert parsed.scheme == 'https' and parsed.netloc",
        "auto_fixable": True,
    },
    "PY_INSECURE_DESERIALISE": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-502",
        "message": "Insecure deserialization: pickle.load/loads or yaml.load() without safe Loader",
        "suggestion": "Never unpickle untrusted data. For YAML: use yaml.safe_load() instead of yaml.load().",
        "auto_fixable": False,
    },
    "PY_CMD_INJECTION": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-78",
        "message": "Command injection risk: os.system/os.popen/subprocess with shell=True",
        "suggestion": "Use subprocess.run() with shell=False and a list of arguments. Never pass user-controlled strings to shell=True.",
        "auto_fixable": False,
    },
    "PY_WEAK_CRYPTO": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-327",
        "message": "Weak cryptographic algorithm: MD5 or SHA-1 used — not suitable for security purposes",
        "suggestion": "Use hashlib.sha256() or higher. For password hashing use bcrypt/argon2 via the cryptography package.",
        "auto_fixable": False,
    },
    "PY_MISSING_TLS_VERIFY": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-295",
        "message": "TLS certificate verification disabled: requests called with verify=False",
        "suggestion": "Remove verify=False. If using a private CA, pass verify='/path/to/ca-bundle.crt' instead.",
        "auto_fixable": True,
    },
    "PY_XXE_RISK": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-611",
        "message": "XML parsing without XXE protection — xml.etree.ElementTree is vulnerable to XXE attacks",
        "suggestion": "Use defusedxml: pip install defusedxml; import defusedxml.ElementTree as ET",
        "auto_fixable": False,
    },
    "PY_SQL_INJECTION": {
        "severity": "HIGH", "language": "python", "cwe": "CWE-89",
        "message": "Possible SQL injection — string formatting used to build a SQL query",
        "suggestion": "Use parameterised queries: cursor.execute('SELECT * FROM t WHERE id = %s', (user_id,))",
        "auto_fixable": False,
    },
    "PY_LOG_INJECTION": {
        "severity": "MEDIUM", "language": "python", "cwe": "CWE-117",
        "message": "User-controlled value logged without sanitization — potential log injection",
        "suggestion": "Sanitize input before logging: strip control characters, truncate, and mask PII.",
        "auto_fixable": False,
    },
    "PY_SILENT_EXCEPT": {
        "severity": "MEDIUM", "language": "python", "cwe": "CWE-390",
        "message": "Silent exception swallowing: except block with only 'pass' — errors are hidden",
        "suggestion": "Add at minimum: logger.debug('Suppressed exception', exc_info=True) in the except block.",
        "auto_fixable": True,
    },
    "PY_SENSITIVE_IN_RESPONSE": {
        "severity": "MEDIUM", "language": "python", "cwe": "CWE-200",
        "message": "Sensitive key name in function return value — may expose secrets to caller",
        "suggestion": "Remove or mask sensitive fields from returned dicts. Never return raw passwords, tokens, or full card numbers.",
        "auto_fixable": False,
    },
    "PY_MISSING_INPUT_VALIDATION": {
        "severity": "MEDIUM", "language": "python", "cwe": "CWE-20",
        "message": "Event parameter used in AWS API call without format validation",
        "suggestion": "Validate contact/resource IDs match expected format (UUID regex) before passing to AWS SDK.",
        "auto_fixable": False,
    },

    # ── Node.js / TypeScript ──────────────────────────────────────────────────
    "JS_PII_IN_LOG": {
        "severity": "CRITICAL", "language": "nodejs", "cwe": "CWE-532",
        "message": "Full event or request body serialised directly to console.log — PII/sensitive data exposure",
        "suggestion": "Use a redactEvent() helper to mask sensitive keys before logging.",
        "auto_fixable": False,
    },
    "JS_HARDCODED_SECRET": {
        "severity": "CRITICAL", "language": "nodejs", "cwe": "CWE-798",
        "message": "Possible hardcoded secret — sensitive variable assigned a string literal",
        "suggestion": "Use AWS Secrets Manager or SSM Parameter Store. Fetch at runtime via @aws-sdk/client-secrets-manager.",
        "auto_fixable": False,
    },
    "JS_EVAL_RISK": {
        "severity": "CRITICAL", "language": "nodejs", "cwe": "CWE-95",
        "message": "eval() called — code injection risk",
        "suggestion": "Remove eval(). Use JSON.parse() for data, or restructure logic to avoid dynamic code execution.",
        "auto_fixable": False,
    },
    "JS_SSRF_RISK": {
        "severity": "HIGH", "language": "nodejs", "cwe": "CWE-918",
        "message": "HTTP request made with URL from event/environment without scheme validation",
        "suggestion": "Validate URL before fetch: const u = new URL(url); if (u.protocol !== 'https:') throw new Error('HTTPS required')",
        "auto_fixable": False,
    },
    "JS_MISSING_TLS_VERIFY": {
        "severity": "HIGH", "language": "nodejs", "cwe": "CWE-295",
        "message": "TLS verification disabled: rejectUnauthorized: false",
        "suggestion": "Remove rejectUnauthorized: false. If testing locally use a self-signed cert bundle instead.",
        "auto_fixable": False,
    },
    "JS_CMD_INJECTION": {
        "severity": "HIGH", "language": "nodejs", "cwe": "CWE-78",
        "message": "Command injection risk: child_process.exec/execSync with shell interpolation",
        "suggestion": "Use execFile() or spawn() with an argument array instead of shell string interpolation.",
        "auto_fixable": False,
    },
    "JS_SQL_INJECTION": {
        "severity": "HIGH", "language": "nodejs", "cwe": "CWE-89",
        "message": "Possible SQL injection — template literal or string concatenation used to build SQL",
        "suggestion": "Use parameterised queries: db.query('SELECT * FROM t WHERE id = $1', [userId])",
        "auto_fixable": False,
    },
    "JS_LOG_INJECTION": {
        "severity": "MEDIUM", "language": "nodejs", "cwe": "CWE-117",
        "message": "User-controlled event field interpolated directly into log string",
        "suggestion": "Sanitize event values before logging. Strip newline/tab characters from strings.",
        "auto_fixable": False,
    },
    "JS_SILENT_CATCH": {
        "severity": "MEDIUM", "language": "nodejs", "cwe": "CWE-390",
        "message": "Empty catch block — errors are silently discarded",
        "suggestion": "Add at minimum: console.error('Suppressed error:', err) in the catch block.",
        "auto_fixable": False,
    },
    "JS_SENSITIVE_IN_RESPONSE": {
        "severity": "MEDIUM", "language": "nodejs", "cwe": "CWE-200",
        "message": "Sensitive field name in returned object — may expose secrets to caller",
        "suggestion": "Remove or mask sensitive fields from response objects.",
        "auto_fixable": False,
    },

    # ── Go ────────────────────────────────────────────────────────────────────
    "GO_PII_IN_LOG": {
        "severity": "CRITICAL", "language": "go", "cwe": "CWE-532",
        "message": "Full request/event struct logged with %v or %+v — PII/sensitive data exposure",
        "suggestion": "Implement a Redact() method or log only specific safe fields.",
        "auto_fixable": False,
    },
    "GO_HARDCODED_SECRET": {
        "severity": "CRITICAL", "language": "go", "cwe": "CWE-798",
        "message": "Possible hardcoded secret — sensitive variable assigned a string literal",
        "suggestion": "Use AWS Secrets Manager. Fetch at init() with secretsmanager.GetSecretValue.",
        "auto_fixable": False,
    },
    "GO_MISSING_TLS_VERIFY": {
        "severity": "HIGH", "language": "go", "cwe": "CWE-295",
        "message": "TLS verification disabled: InsecureSkipVerify: true",
        "suggestion": "Remove InsecureSkipVerify. For custom CAs use tls.Config{RootCAs: certPool}.",
        "auto_fixable": False,
    },
    "GO_CMD_INJECTION": {
        "severity": "HIGH", "language": "go", "cwe": "CWE-78",
        "message": "Command injection risk: exec.Command with user-controlled string",
        "suggestion": "Never pass user input to exec.Command. Use argument arrays and validate each argument.",
        "auto_fixable": False,
    },
    "GO_WEAK_CRYPTO": {
        "severity": "HIGH", "language": "go", "cwe": "CWE-327",
        "message": "Weak cryptographic algorithm: crypto/md5 or crypto/sha1 used",
        "suggestion": "Use crypto/sha256 or crypto/sha512. For password hashing use golang.org/x/crypto/bcrypt.",
        "auto_fixable": False,
    },
    "GO_SQL_INJECTION": {
        "severity": "HIGH", "language": "go", "cwe": "CWE-89",
        "message": "Possible SQL injection — fmt.Sprintf used to build SQL query string",
        "suggestion": "Use parameterised queries: db.QueryContext(ctx, 'SELECT * FROM t WHERE id = $1', userID)",
        "auto_fixable": False,
    },
    "GO_SILENT_ERROR": {
        "severity": "MEDIUM", "language": "go", "cwe": "CWE-390",
        "message": "Error silently discarded with blank identifier: _ = err",
        "suggestion": "Handle or log the error: if err != nil { log.Printf(\"operation failed: %v\", err) }",
        "auto_fixable": False,
    },
    "GO_LOG_INJECTION": {
        "severity": "MEDIUM", "language": "go", "cwe": "CWE-117",
        "message": "User-controlled value passed to log.Printf — potential log injection",
        "suggestion": "Sanitize or truncate user input before logging. Use %q for safe string quoting.",
        "auto_fixable": False,
    },

    # ── Java / Spring ─────────────────────────────────────────────────────────
    "JAVA_PII_IN_LOG": {
        "severity": "CRITICAL", "language": "java", "cwe": "CWE-532",
        "message": "Full request/event object logged with toString() or directly — PII/sensitive data exposure",
        "suggestion": "Implement a custom toString() that masks sensitive fields, or log only safe individual fields.",
        "auto_fixable": False,
    },
    "JAVA_HARDCODED_SECRET": {
        "severity": "CRITICAL", "language": "java", "cwe": "CWE-798",
        "message": "Possible hardcoded secret — sensitive field assigned a string literal",
        "suggestion": "Use AWS Secrets Manager. Inject via @Value from Secrets Manager property source.",
        "auto_fixable": False,
    },
    "JAVA_CMD_INJECTION": {
        "severity": "HIGH", "language": "java", "cwe": "CWE-78",
        "message": "Command injection risk: Runtime.exec() or ProcessBuilder with user input",
        "suggestion": "Avoid Runtime.exec(). If unavoidable, use ProcessBuilder with an explicit argument list.",
        "auto_fixable": False,
    },
    "JAVA_MISSING_TLS_VERIFY": {
        "severity": "HIGH", "language": "java", "cwe": "CWE-295",
        "message": "TLS verification disabled: TrustAllCerts or NoopHostnameVerifier in use",
        "suggestion": "Remove trust-all TLS config. Use a proper TrustStore with your CA certificates.",
        "auto_fixable": False,
    },
    "JAVA_WEAK_CRYPTO": {
        "severity": "HIGH", "language": "java", "cwe": "CWE-327",
        "message": "Weak cryptographic algorithm: MD5 or SHA-1 MessageDigest in use",
        "suggestion": "Use MessageDigest.getInstance(\"SHA-256\") or higher. For passwords use BCryptPasswordEncoder.",
        "auto_fixable": False,
    },
    "JAVA_XXE_RISK": {
        "severity": "HIGH", "language": "java", "cwe": "CWE-611",
        "message": "XXE risk: DocumentBuilderFactory or SAXParserFactory without XXE protection features disabled",
        "suggestion": "Call dbf.setFeature(\"http://apache.org/xml/features/disallow-doctype-decl\", true) before parsing.",
        "auto_fixable": False,
    },
    "JAVA_SQL_INJECTION": {
        "severity": "HIGH", "language": "java", "cwe": "CWE-89",
        "message": "Possible SQL injection — string concatenation used to build SQL query",
        "suggestion": "Use PreparedStatement: pstmt = conn.prepareStatement(\"SELECT * FROM t WHERE id = ?\"); pstmt.setString(1, userId)",
        "auto_fixable": False,
    },
    "JAVA_SILENT_CATCH": {
        "severity": "MEDIUM", "language": "java", "cwe": "CWE-390",
        "message": "Empty catch block — exception silently swallowed",
        "suggestion": "Add at minimum: logger.debug(\"Suppressed exception\", e) in the catch block.",
        "auto_fixable": False,
    },
    "JAVA_LOG_INJECTION": {
        "severity": "MEDIUM", "language": "java", "cwe": "CWE-117",
        "message": "User-controlled value concatenated directly into log statement",
        "suggestion": "Sanitize input before logging. Strip newline/tab characters. Use parameterised logging: log.info(\"msg: {}\", sanitize(input))",
        "auto_fixable": False,
    },
}

LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception"}
PY_SECRET_NAMES = {
    "password", "passwd", "secret", "api_key", "apikey", "access_key", "private_key",
    "auth_token", "credentials", "client_secret",
}
PY_SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "api_key", "private_key", "access_key", "credentials"}
PY_SQL_METHODS = {"execute", "executemany", "query", "raw", "cursor"}
PY_AWS_CLIENTS = {"_CONNECT_CLIENT", "_S3_CLIENT"}
SEVERITY_COLORS = {
    "CRITICAL": "\033[91m",
    "HIGH": "\033[93m",
    "MEDIUM": "\033[94m",
    "LOW": "\033[96m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
SUCCESS = "\033[92m"


@dataclass
class Issue:
    rule_id: str
    severity: str
    line: int
    col: int
    message: str
    suggestion: str
    cwe: str
    auto_fixable: bool

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class ImportTracker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.xml_etree_line: Optional[int] = None
        self.defusedxml_imported = False
        self.hashlib_imports = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "xml.etree.ElementTree" or alias.name.startswith("xml.etree"):
                self.xml_etree_line = self.xml_etree_line or node.lineno
            if alias.name.startswith("defusedxml"):
                self.defusedxml_imported = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module.startswith("xml.etree"):
            self.xml_etree_line = self.xml_etree_line or node.lineno
        if module.startswith("defusedxml"):
            self.defusedxml_imported = True
        if module == "hashlib":
            for alias in node.names:
                self.hashlib_imports.add(alias.asname or alias.name)


def _color(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{RESET}"


def _line_no_from_pos(source: str, pos: int) -> int:
    return source.count("\n", 0, pos) + 1


def _full_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _full_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _is_log_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_event_get(node: ast.AST, owner_names: Sequence[str] = ("event", "params")) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in owner_names
    )


def _is_event_subscript(node: ast.AST, owner_names: Sequence[str] = ("event", "params")) -> bool:
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in owner_names


def _is_direct_event_value(node: ast.AST) -> bool:
    return _is_event_get(node) or _is_event_subscript(node)


def _contains_validation_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn_name = (_full_name(child.func) or "").lower()
            if any(token in fn_name for token in ("validate", "check", "regex", "match", "fullmatch")):
                return True
    return False


def _is_json_dumps_event(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dumps"
        and _full_name(node.func.value) == "json"
        and bool(node.args)
        and _is_name(node.args[0], "event")
    )


def _is_str_event(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _full_name(node.func) == "str" and bool(node.args) and _is_name(node.args[0], "event")


def _looks_like_sql_string(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b", node.value, re.IGNORECASE))
    if isinstance(node, ast.JoinedStr):
        rendered = "".join(value.value for value in node.values if isinstance(value, ast.Constant) and isinstance(value.value, str))
        return bool(re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b", rendered, re.IGNORECASE))
    return False


def _is_dynamic_sql(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return _looks_like_sql_string(node.left) or _looks_like_sql_string(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _looks_like_sql_string(node.func.value)
    return False


def _find_function(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _preceding_lines(source_lines: List[str], lineno: int, limit: int = 5) -> str:
    start = max(0, lineno - 1 - limit)
    return "\n".join(source_lines[start:lineno - 1]).lower()


def _make_issue(rule_id: str, line: int, col: int = 0) -> Issue:
    rule = RULES[rule_id]
    return Issue(
        rule_id=rule_id,
        severity=str(rule["severity"]),
        line=line,
        col=col,
        message=str(rule["message"]),
        suggestion=str(rule["suggestion"]),
        cwe=str(rule["cwe"]),
        auto_fixable=bool(rule["auto_fixable"]),
    )


def audit_python(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [], f"SyntaxError in {path}: {exc}"

    tracker = ImportTracker()
    tracker.visit(tree)
    issues: List[Issue] = []
    seen = set()
    source_lines = source.splitlines()

    def add(rule_id: str, line: int, col: int = 0) -> None:
        key = (rule_id, line, col)
        if key in seen:
            return
        seen.add(key)
        issues.append(_make_issue(rule_id, line, col))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = _full_name(node.func) or ""

            if _is_log_call(node):
                format_arg = node.args[0] if node.args else None
                if any(_is_json_dumps_event(arg) or _is_name(arg, "event") or _is_str_event(arg) for arg in node.args):
                    add("PY_PII_IN_LOG", node.lineno, getattr(node, "col_offset", 0))
                if isinstance(format_arg, ast.Constant) and isinstance(format_arg.value, str) and ("%s" in format_arg.value or "{}" in format_arg.value):
                    for arg in node.args[1:]:
                        if _is_direct_event_value(arg):
                            add("PY_LOG_INJECTION", node.lineno, getattr(node, "col_offset", 0))
                            break

            if fn_name in {"eval", "exec"}:
                add("PY_EVAL_EXEC", node.lineno, getattr(node, "col_offset", 0))

            if fn_name in {"urllib.request.urlopen", "urlopen"}:
                context = _preceding_lines(source_lines, node.lineno)
                if "urlparse(" not in context or ".scheme" not in context:
                    add("PY_SSRF_URLOPEN", node.lineno, getattr(node, "col_offset", 0))

            if fn_name in {"pickle.load", "pickle.loads", "pickle.Unpickler"}:
                add("PY_INSECURE_DESERIALISE", node.lineno, getattr(node, "col_offset", 0))
            if fn_name == "yaml.load" and not any(kw.arg == "Loader" for kw in node.keywords):
                add("PY_INSECURE_DESERIALISE", node.lineno, getattr(node, "col_offset", 0))

            if fn_name in {"os.system", "os.popen", "os.popen2", "os.popen3", "os.popen4"}:
                add("PY_CMD_INJECTION", node.lineno, getattr(node, "col_offset", 0))
            if fn_name in {"subprocess.run", "subprocess.call", "subprocess.Popen", "subprocess.check_output", "subprocess.check_call"}:
                if any(kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True for kw in node.keywords):
                    add("PY_CMD_INJECTION", node.lineno, getattr(node, "col_offset", 0))

            if fn_name in {"hashlib.md5", "hashlib.sha1"} or fn_name in tracker.hashlib_imports.intersection({"md5", "sha1"}):
                add("PY_WEAK_CRYPTO", node.lineno, getattr(node, "col_offset", 0))

            if fn_name in {"requests.get", "requests.post", "requests.put", "requests.patch", "requests.delete", "requests.request"}:
                if any(kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False for kw in node.keywords):
                    add("PY_MISSING_TLS_VERIFY", node.lineno, getattr(node, "col_offset", 0))

            if isinstance(node.func, ast.Attribute) and node.func.attr in PY_SQL_METHODS:
                for arg in node.args:
                    if _is_dynamic_sql(arg):
                        add("PY_SQL_INJECTION", node.lineno, getattr(node, "col_offset", 0))
                        break

            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in PY_AWS_CLIENTS:
                for value in [*node.args, *(kw.value for kw in node.keywords)]:
                    if _is_direct_event_value(value) and not _contains_validation_call(value):
                        add("PY_MISSING_INPUT_VALIDATION", node.lineno, getattr(node, "col_offset", 0))
                        break

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and len(value.value) > 3:
                for target in targets:
                    if isinstance(target, ast.Name) and any(secret in target.id.lower() for secret in PY_SECRET_NAMES):
                        add("PY_HARDCODED_SECRET", node.lineno, getattr(node, "col_offset", 0))
                        break

        if isinstance(node, ast.ExceptHandler):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                add("PY_SILENT_EXCEPT", node.lineno, getattr(node, "col_offset", 0))

        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.lower() in PY_SENSITIVE_KEYS:
                    add("PY_SENSITIVE_IN_RESPONSE", node.lineno, getattr(node, "col_offset", 0))
                    break

    if tracker.xml_etree_line and not tracker.defusedxml_imported:
        add("PY_XXE_RISK", tracker.xml_etree_line, 0)

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


def _collect_regex_issues(source: str, patterns: Sequence[Tuple[str, str, int]]) -> List[Tuple[str, int]]:
    findings: List[Tuple[str, int]] = []
    seen = set()
    for rule_id, pattern, flags in patterns:
        for match in re.finditer(pattern, source, flags):
            line = _line_no_from_pos(source, match.start())
            key = (rule_id, line)
            if key in seen:
                continue
            seen.add(key)
            findings.append((rule_id, line))
    return findings


def audit_nodejs(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    patterns = [
        ("JS_PII_IN_LOG", r"console\.log\s*\(\s*JSON\.stringify\s*\(\s*event\b|console\.\w+\s*\(.*JSON\.stringify\s*\(\s*event\b", re.MULTILINE),
        ("JS_HARDCODED_SECRET", r"(?:const|let|var)\s+(?:password|passwd|secret|apiKey|api_key|accessKey|privateKey|authToken|clientSecret)\s*=\s*['\"][^'\"]{4,}['\"]", re.MULTILINE),
        ("JS_EVAL_RISK", r"\beval\s*\(", re.MULTILINE),
        ("JS_SSRF_RISK", r"(?:fetch|axios\.get|axios\.post|axios\.request|https?\.request|https?\.get)\s*\(\s*(?:event|req|request|url|endpoint)", re.MULTILINE),
        ("JS_MISSING_TLS_VERIFY", r"rejectUnauthorized\s*:\s*false", re.MULTILINE),
        ("JS_CMD_INJECTION", r"(?:exec|execSync)\s*\(\s*(?:.*\+|`.*\$\{)", re.MULTILINE),
        ("JS_SQL_INJECTION", r"`.*SELECT.*\$\{|`.*INSERT.*\$\{|`.*UPDATE.*\$\{|`.*DELETE.*\$\{|['\"].*SELECT.*['\"]\s*\+|['\"].*INSERT.*['\"]\s*\+", re.MULTILINE | re.IGNORECASE),
        ("JS_LOG_INJECTION", r"console\.\w+\s*\(.*\$\{event\.|console\.\w+\s*\(.*\+\s*event\.", re.MULTILINE),
        ("JS_SILENT_CATCH", r"catch\s*\([^)]*\)\s*\{\s*\}", re.MULTILINE),
        ("JS_SENSITIVE_IN_RESPONSE", r"(?:return|resolve)\s*\(?\s*\{[\s\S]{0,200}?(?:password|passwd|secret|token|apiKey|api_key|privateKey)\s*:\s*(?!['\"]?\*{3})", re.MULTILINE | re.IGNORECASE),
    ]
    issues = [_make_issue(rule_id, line) for rule_id, line in _collect_regex_issues(source, patterns)]
    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


def audit_go(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    patterns = [
        ("GO_PII_IN_LOG", r"(?:log|fmt)\.\w*[Pp]rintf?\s*\(.*%[v+].*(?:event|request|req|input|body)|fmt\.Println\s*\(.*(?:event|request|req)", re.MULTILINE),
        ("GO_HARDCODED_SECRET", r"(?:password|passwd|secret|apiKey|api_key|accessKey|privateKey|authToken)\s*(?::=|=)\s*\"[^\"]{4,}\"", re.MULTILINE),
        ("GO_MISSING_TLS_VERIFY", r"InsecureSkipVerify\s*:\s*true", re.MULTILINE),
        ("GO_CMD_INJECTION", r"exec\.Command\s*\(", re.MULTILINE),
        ("GO_WEAK_CRYPTO", r"(?:crypto/md5|crypto/sha1|\"crypto/md5\"|\"crypto/sha1\"|md5\.New\(\)|sha1\.New\(\))", re.MULTILINE),
        ("GO_SQL_INJECTION", r"fmt\.Sprintf\s*\(.*(?:SELECT|INSERT|UPDATE|DELETE|WHERE)", re.MULTILINE | re.IGNORECASE),
        ("GO_SILENT_ERROR", r"_\s*=\s*(?:err\b|\w+\.(?:Close|Write|Read|Exec|Query)\s*\()", re.MULTILINE),
        ("GO_LOG_INJECTION", r"log\.\w*[Pp]rintf?\s*\(.*(?:request|event|input|body|userInput)", re.MULTILINE),
    ]
    issues = [_make_issue(rule_id, line) for rule_id, line in _collect_regex_issues(source, patterns)]
    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


def audit_java(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    patterns = [
        ("JAVA_PII_IN_LOG", r"log\.\w+\s*\(.*\.toString\(\)|log\.\w+\s*\(.*(?:request|event|input)[\s,)]", re.MULTILINE),
        ("JAVA_HARDCODED_SECRET", r"(?:String|private static final String)\s+(?:password|passwd|secret|apiKey|api_key|accessKey|privateKey|authToken)\s*=\s*\"[^\"]{4,}\"", re.MULTILINE),
        ("JAVA_CMD_INJECTION", r"Runtime\.getRuntime\(\)\.exec\s*\(|new\s+ProcessBuilder\s*\(", re.MULTILINE),
        ("JAVA_MISSING_TLS_VERIFY", r"(?:TrustAllCerts|NoopHostnameVerifier|ALLOW_ALL_HOSTNAME_VERIFIER|trustAllCerts|SSLSocketFactory\.SSL_SOCKET_FACTORY)", re.MULTILINE),
        ("JAVA_WEAK_CRYPTO", r"MessageDigest\.getInstance\s*\(\s*\"(?:MD5|SHA-1|SHA1)\"\s*\)", re.MULTILINE),
        ("JAVA_SQL_INJECTION", r"\".*(?:SELECT|INSERT|UPDATE|DELETE).*\"\s*\+|String\.format\s*\(.*(?:SELECT|INSERT|UPDATE|DELETE)", re.MULTILINE | re.IGNORECASE),
        ("JAVA_SILENT_CATCH", r"catch\s*\([^)]+\)\s*\{\s*\}", re.MULTILINE),
        ("JAVA_LOG_INJECTION", r"log\.\w+\s*\(.*\+\s*(?:request|event|input|userInput|param)", re.MULTILINE),
    ]
    issues = [_make_issue(rule_id, line) for rule_id, line in _collect_regex_issues(source, patterns)]
    lines = source.splitlines()
    for idx, line in enumerate(lines, 1):
        if re.search(r"DocumentBuilderFactory\.newInstance\(\)|SAXParserFactory\.newInstance\(\)|XMLInputFactory\.newInstance\(\)", line):
            window = "\n".join(lines[idx - 1:min(len(lines), idx + 9)])
            if not re.search(r"setFeature.*disallow-doctype", window):
                issues.append(_make_issue("JAVA_XXE_RISK", idx))
    deduped = {(issue.rule_id, issue.line): issue for issue in issues}
    ordered = sorted(deduped.values(), key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return ordered, None


def detect_language(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    if ext in (".js", ".mjs", ".cjs", ".ts"):
        return "nodejs"
    if ext == ".go":
        return "go"
    if ext == ".java":
        return "java"
    return None


def audit_file(path: Path) -> Tuple[List[Issue], Optional[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], f"File not found: {path}"
    except OSError as exc:
        return [], f"Cannot read file: {exc}"

    language = detect_language(path)
    if language is None:
        return [], f"Unsupported file type '{path.suffix}' — supported: .py .js .mjs .cjs .ts .go .java"

    if language == "python":
        return audit_python(path, source)
    if language == "nodejs":
        return audit_nodejs(path, source)
    if language == "go":
        return audit_go(path, source)
    if language == "java":
        return audit_java(path, source)
    return [], f"No auditor for language: {language}"


def print_report(path: Path, issues: List[Issue], error: Optional[str], summary_only: bool = False) -> None:
    lang = detect_language(path) or "unknown"
    print(f"\n{BOLD}{path}{RESET}  [{lang}]")
    if error:
        print(f"  ✗ {_color('ERROR', SEVERITY_COLORS['CRITICAL'])}: {error}")
        return
    if not issues:
        print(f"  {_color('✓ No issues found', SUCCESS)}")
        return
    if summary_only:
        by_severity: Dict[str, int] = {}
        for issue in issues:
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        parts = [
            f"{_color(severity, SEVERITY_COLORS.get(severity, ''))}: {count}"
            for severity, count in sorted(by_severity.items(), key=lambda item: SEVERITY_ORDER.get(item[0], 9))
        ]
        print(f"  {', '.join(parts)}  ({len(issues)} total)")
        return
    for issue in issues:
        fix_str = " [auto-fixable]" if issue.auto_fixable else ""
        owasp = CWE_TO_OWASP.get(issue.cwe, "")
        print(f"  Line {issue.line:4d}  {_color(f'[{issue.severity}]', SEVERITY_COLORS.get(issue.severity, ''))} {issue.rule_id}  ({issue.cwe}){fix_str}")
        print(f"           {issue.message}")
        print(f"           → {issue.suggestion}")
        if owasp:
            print(f"           OWASP: {owasp}")


def print_json_report(results: Dict[str, object]) -> None:
    print(json.dumps(results, indent=2))


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    output_json = "--json" in args
    summary_only = "--summary" in args
    file_args = [arg for arg in args if not arg.startswith("--")]
    if not file_args:
        print("Error: no input files specified", file=sys.stderr)
        return 2

    all_results: Dict[str, Dict[str, object]] = {}
    exit_code = 0

    for file_arg in file_args:
        path = Path(file_arg)
        issues, error = audit_file(path)
        all_results[str(path)] = {
            "language": detect_language(path),
            "issues": [
                {**issue.as_dict(), "owasp": CWE_TO_OWASP.get(issue.cwe, "")}
                for issue in issues
            ],
            "error": error,
            "counts": {
                "CRITICAL": sum(1 for issue in issues if issue.severity == "CRITICAL"),
                "HIGH": sum(1 for issue in issues if issue.severity == "HIGH"),
                "MEDIUM": sum(1 for issue in issues if issue.severity == "MEDIUM"),
                "LOW": sum(1 for issue in issues if issue.severity == "LOW"),
            },
        }
        if error:
            exit_code = 2
        elif any(issue.severity in ("CRITICAL", "HIGH") for issue in issues):
            exit_code = max(exit_code, 1)
        if not output_json:
            print_report(path, issues, error, summary_only)

    if output_json:
        print_json_report(all_results)
    else:
        total_critical = sum(result["counts"]["CRITICAL"] for result in all_results.values())
        total_high = sum(result["counts"]["HIGH"] for result in all_results.values())
        total_medium = sum(result["counts"]["MEDIUM"] for result in all_results.values())
        total_low = sum(result["counts"]["LOW"] for result in all_results.values())
        print(f"\n{'─' * 60}")
        print(
            f"Total: {_color(str(total_critical) + ' CRITICAL', SEVERITY_COLORS['CRITICAL'])}  "
            f"{_color(str(total_high) + ' HIGH', SEVERITY_COLORS['HIGH'])}  "
            f"{_color(str(total_medium) + ' MEDIUM', SEVERITY_COLORS['MEDIUM'])}  "
            f"{_color(str(total_low) + ' LOW', SEVERITY_COLORS['LOW'])}"
        )
        if exit_code == 0:
            print(_color("✓ All files pass CRITICAL/HIGH checks", SUCCESS))
        else:
            print(_color("✗ Fix CRITICAL/HIGH issues before deployment", SEVERITY_COLORS["CRITICAL"]))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
