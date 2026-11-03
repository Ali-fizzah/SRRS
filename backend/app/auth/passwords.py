"""Password hashing with bcrypt (plan §4)."""

import bcrypt

# bcrypt only looks at the first 72 bytes; longer passwords are refused, not truncated.
MAX_PASSWORD_BYTES = 72

# Compared against when the email is unknown, so a wrong email takes as long as a
# wrong password and response time does not reveal which accounts exist.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password longer than {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    matched = bcrypt.checkpw(raw, (password_hash or _DUMMY_HASH).encode())
    return matched and password_hash is not None
