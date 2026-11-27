"""The household's import password (issue #817): what tells apart two outside
accounts whose numbers end in the same four digits, without the numbers.

Every import keeps only an account number's last four digits (#815). Two
accounts of one source that end alike would then share one name, and one
mapping row. With an import password set, each number also gets a short
fingerprint beside its last four (``...4321#kqzmtbe``): a keyed hash of the
whole number, under a key made from the password.

The key, not a plain hash, is what keeps the number out of the data repo: an
account number is one of a billion or so, and its last four are shown, so a
plain hash of it is undone by trying them all in well under a second. The
password goes through Argon2id, which is slow and needs much memory on
purpose, so that each guess at it costs as much; the number is then hashed
quickly under the key it makes. There is no lockout and no one watching, as
a bank has, so a long passphrase and a private data repo do the rest.

Kept in the data repo, ``imports/import_password.toml``: the salt, Argon2id's
settings, a check value and who set it, so that every person of the household who gives
the same password gets the same key, and a wrong one is caught rather than
quietly giving new names. Kept in each person's own settings
(``user_config``): the key made from it, never the password. It is used only
by imports; losing it means only answering the mapping questions again.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw

from zabob.retirement import user_config
from zabob.retirement.oscompat import login_name

__all__ = [
    "FILE", "ImportKeyError", "Settings", "SETTINGS", "fingerprint", "is_set", "key", "set_password",
]

FILE = "import_password.toml"
"""In the data dir's ``imports/``: the salt, the settings and the check value."""

_CHECK = b"zabob-retirement import password check"
# Seven letters: about 33 bits, so two of one household's accounts share a
# fingerprint about once in eight billion pairs. Letters only, so a masked
# name has no run of digits to be taken for a number again.
_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_LENGTH = 7


class ImportKeyError(ValueError):
    """The data repo's imports use a password this user hasn't given, or the
    one they gave isn't it."""


@dataclass(frozen=True)
class Settings:
    """Argon2id's settings: about a second, and 256 MiB, on a laptop of 2026.
    Kept with the salt, so every machine makes the same key."""

    memory_kib: int = 262_144
    iterations: int = 3
    lanes: int = 4


SETTINGS = Settings()
"""What a new import password is made with (tests make it cheap)."""

_MAX_LANES = 64
_MAX_ITERATIONS = 64
_MAX_MEMORY_KIB = 4 * 1024 * 1024  # 4 GiB, sixteen times the default


def _path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "imports" / FILE


def _read(data_dir: Path | str) -> tuple[bytes, Settings, str, str | None] | None:
    """The data repo's ``(salt, settings, check, set_by)``, or None when its
    imports use no password."""
    path = _path(data_dir)
    if not path.is_file():
        return None
    try:
        found = tomllib.loads(path.read_text(encoding="utf-8"))
        settings = Settings(int(found["memory_kib"]), int(found["iterations"]), int(found["lanes"]))
        # Argon2's own limits, and ones well past any key worth waiting for:
        # an edited or badly merged file is refused here, not met as argon2's
        # error (not a ValueError) or as an import that takes all the memory.
        if not (1 <= settings.lanes <= _MAX_LANES and 1 <= settings.iterations <= _MAX_ITERATIONS
                and 8 * settings.lanes <= settings.memory_kib <= _MAX_MEMORY_KIB):
            raise ValueError(f"Argon2 settings out of range: {settings}")
        return (bytes.fromhex(str(found["salt"])), settings,
                bytes.fromhex(str(found["check"])).hex(),
                str(found["set_by"]) if "set_by" in found else None)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, ValueError, TypeError) as e:
        raise ImportKeyError(f"{path} can't be read ({type(e).__name__}: {e}); it should be as "
                             "`sim login --import-password` wrote it") from None


def _derive(password: str, salt: bytes, settings: Settings) -> bytes:
    return hash_secret_raw(
        password.encode("utf-8"), salt, time_cost=settings.iterations, memory_cost=settings.memory_kib,
        parallelism=settings.lanes, hash_len=32, type=Type.ID)


def _check(derived: bytes) -> str:
    return hmac.new(derived, _CHECK, hashlib.sha256).hexdigest()


def is_set(data_dir: Path | str) -> bool:
    """Whether the data repo's imports use a password."""
    return _read(data_dir) is not None


def set_password(data_dir: Path | str, password: str) -> bool:
    """Make this user's key from ``password``, and keep it in their settings.
    The data repo's first password makes its salt and check value (True is
    returned); after that ``password`` must be that one, or ImportKeyError."""
    if not password:
        raise ImportKeyError("the import password can't be empty")
    found = _read(data_dir)
    salt, settings, check, set_by = found or (secrets.token_bytes(16), SETTINGS, None, None)
    derived = _derive(password, salt, settings)
    if check is not None and not hmac.compare_digest(_check(derived), check):
        raise ImportKeyError(
            f"that isn't this data repo's import password: it is the one {set_by or 'whoever set it first'} "
            f"gave, recorded in {_path(data_dir)}")
    if found is None:
        path = _path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# The import password's salt, settings and check value (sim login --import-password).\n"
            "# The password itself is never kept here. See docs/guides/importing-data.md.\n"
            f'salt = "{salt.hex()}"\nmemory_kib = {settings.memory_kib}\niterations = {settings.iterations}\n'
            f'lanes = {settings.lanes}\ncheck = "{_check(derived)}"\n'
            # Who set it, so a household can tell whom to ask (a JSON string is a TOML one).
            f'set_by = {json.dumps(user_config.current_user() or login_name())}\n', encoding="utf-8")
    user_config.write_import_key(data_dir, derived.hex())
    return found is None


def key(data_dir: Path | str) -> bytes | None:
    """The key imports into this data repo fingerprint account numbers
    with; None when its imports use no password. ImportKeyError when they do
    and this user hasn't given it, or gave another since it was changed."""
    found = _read(data_dir)
    if found is None:
        return None
    held = user_config.read_import_key(data_dir)
    if held is None:
        raise ImportKeyError(
            "this data repo's imports use an import password, which tells apart accounts whose numbers end "
            "in the same four digits; give it once with `sim login --import-password` "
            f"({found[3] or 'whoever set it'} knows it). It is used only by imports")
    try:
        derived = bytes.fromhex(held)
    except ValueError:
        derived = b""
    if not hmac.compare_digest(_check(derived), found[2]):
        raise ImportKeyError(
            "the import password you gave isn't this data repo's any more; give the current one with "
            "`sim login --import-password`")
    return derived


def fingerprint(secret: bytes, digits: str) -> str:
    """Seven letters for the whole account number ``digits``, under ``secret``."""
    value = int.from_bytes(hmac.new(secret, digits.encode("ascii"), hashlib.sha256).digest()[:8], "big")
    letters = []
    for _ in range(_LENGTH):
        value, at = divmod(value, len(_LETTERS))
        letters.append(_LETTERS[at])
    return "".join(letters)
