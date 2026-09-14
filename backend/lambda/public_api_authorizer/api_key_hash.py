"""Deterministic scrypt digest for public API keys.

Shared by the Lambda authorizer (`handler.py`) and
`scripts/manage-public-api-keys.py` so mint and verify can never drift.

Why scrypt with a fixed salt, rather than SHA-256 or a per-key salt:

- The digest doubles as the DynamoDB primary key (``pk = APIKEY#<digest>``),
  so it must be deterministic — a per-key random salt would force a table
  scan on every request.
- CodeQL (`py/weak-sensitive-data-hashing`) requires a computationally
  expensive hash for credential material; scrypt is memory-hard, SHA-256
  is not.
- Keys are ~288-bit random tokens (``secrets.token_urlsafe(36)``), not
  user-chosen passwords, so the dictionary/rainbow-table attacks a unique
  salt defends against do not apply here.

Parameters (n=2^14, r=8, p=1) cost roughly 50 ms and 16 MiB per call on the
Lambda ARM64 runtime — comfortably inside the authorizer's 5 s timeout and
256 MB memory, and amortized by API Gateway's 5-minute result cache.
"""

from __future__ import annotations

import hashlib

_SALT = b"lxsoftware-public-api-key-v1"
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def hash_api_key(value: str) -> str:
    """Return the hex scrypt digest used in the ``APIKEY#<digest>`` row key."""
    digest = hashlib.scrypt(
        value.encode("utf-8"),
        salt=_SALT,
        n=_N,
        r=_R,
        p=_P,
        dklen=_DKLEN,
    )
    return digest.hex()
