"""Canonical private storage paths shared by uploads, serving and cleanup."""
from pathlib import Path
import re
import unicodedata

BACKEND_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_ROOT = BACKEND_ROOT / "uploads"
STORAGE_CATEGORIES = frozenset({"documents", "audio", "historical_exams", "tutorials", "solutions"})


def validate_component(value: str, label: str = "path component") -> str:
    if (not isinstance(value, str) or not value or len(value) > 255
            or value in {".", ".."} or value != value.strip()
            or any(c in value for c in '/\\:<>"|?*')
            or any(unicodedata.category(c).startswith("C") for c in value)
            or value.endswith((".", " "))
            or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value)):
        raise ValueError(f"Invalid {label}")
    return value


def build_storage_path(user_id: str, course_id: str, category: str, filename: str) -> str:
    if category not in STORAGE_CATEGORIES:
        raise ValueError("Invalid storage category")
    return "/".join((category, validate_component(user_id, "user ID"),
                     validate_component(course_id, "course ID"), validate_component(filename, "filename")))


def resolve_storage_path(storage_path: str, user_id: str = None, root: Path = None) -> Path:
    if not isinstance(storage_path, str):
        raise ValueError("Invalid storage path")
    parts = storage_path.split("/")
    if len(parts) != 4 or parts[0] not in STORAGE_CATEGORIES:
        raise ValueError("Invalid storage path")
    for part in parts:
        validate_component(part)
    owner = parts[1]
    if user_id is not None and owner != validate_component(user_id, "user ID"):
        raise ValueError("Storage owner mismatch")
    base = Path(root if root is not None else UPLOADS_ROOT).resolve()
    target = base.joinpath(*parts).resolve()
    # Check the resolved owner path as well as raw syntax: directory symlinks
    # must not redirect an owner's object into another user's directory.
    owner_root = base / parts[0] / owner
    if owner_root.resolve() != owner_root or not target.is_relative_to(owner_root):
        raise ValueError("Storage path escapes owner directory")
    return target
