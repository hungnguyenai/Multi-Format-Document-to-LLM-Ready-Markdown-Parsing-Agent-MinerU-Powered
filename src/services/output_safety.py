"""Output safety (S-3 content gate, relocated to node logic).

The 5-layer security model is framework-enforced; there are no developer `_security_gate_*`
methods. The S-3 content checks are a pure function called by PostProcessNode after the payload
is rendered:

  1. Anti-suppression — the parse-quality judge MUST have run (quality_judge_executed).
  2. SecretLeakageGate — credential patterns in extracted text are redacted in place.
  3. Injection / credential markers — prompt-injection or credential markers blank the output.

Returns a dict the node merges into state: {final_output, redaction_triggered, error?}.
"""

from __future__ import annotations

import re

# Secret-leakage redaction patterns (label kept for auditability).
_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "openai-api-key"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "aws-access-key"),
    (re.compile(r"eyJ[a-zA-Z0-9._-]{10,}"), "jwt-token"),
    (re.compile(r"(?i)(password|api_key|token|secret)\s*=\s*[\"'][^\"']{8,}[\"']"), "credential-assignment"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}"), "bearer-token"),
]
_REDACTION_PLACEHOLDER = "[REDACTED - potential secret]"

# Prompt-injection markers (blank the whole output on match).
_INJECTION_PATTERNS = [
    re.compile(r"<\|"),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"IGNORE\s+PREVIOUS\s+INSTRUCTIONS", re.IGNORECASE),
    re.compile(r"</s>"),
    re.compile(r"<\|im_start\|>|<\|im_end\|>"),
]

# Belt-and-suspenders credential markers (after redaction).
_CREDENTIAL_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"eyJ[a-zA-Z0-9._\-]{10,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"(?i)Bearer\s+[a-zA-Z0-9._\-]{20,}"),
]


def apply_output_safety(final_output: str, quality_judge_executed: bool) -> dict:
    """Apply the S-3 content checks to the rendered output.

    Returns {final_output, redaction_triggered, error?}. The caller short-circuits to an error
    status based on `error` and emits the audit trace.
    """
    if not final_output:
        return {"final_output": final_output, "redaction_triggered": False}

    # 1. Anti-suppression: the parse-quality judge must have executed.
    if not quality_judge_executed:
        return {
            "final_output": final_output,
            "redaction_triggered": False,
            "error": ("S-3 violation: quality_judge_executed is False — the parse-quality judge did not execute"),
        }

    # 2. SecretLeakageGate: scan + redact credential patterns in place.
    redaction_triggered = False
    for pattern, _label in _SECRET_PATTERNS:
        new_output, count = re.subn(pattern, _REDACTION_PLACEHOLDER, final_output)
        if count > 0:
            final_output = new_output
            redaction_triggered = True

    # 3. Injection marker check.
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(final_output):
            return {
                "final_output": "[REDACTED — S-3: prompt injection marker in output]",
                "redaction_triggered": redaction_triggered,
                "error": "S-3 violation: injection marker in final_output — redacted",
            }

    # 4. Credential leak check (after redaction pass).
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(final_output):
            return {
                "final_output": "[REDACTED — S-3: credential pattern detected in output]",
                "redaction_triggered": redaction_triggered,
                "error": "S-3 violation: credential pattern in final_output — redacted",
            }

    return {"final_output": final_output, "redaction_triggered": redaction_triggered}
