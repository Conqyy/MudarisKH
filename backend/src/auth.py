"""
Request authentication — verifies Firebase ID tokens on incoming API calls.

Every endpoint that touches user data depends on :func:`require_uid`, which
returns the caller's Firebase uid. The uid comes *only* from a verified token,
never from a request body or path — clients used to pass ``user_id`` themselves,
which meant anyone could read or delete anyone else's data.

The backend talks to Firestore through the Admin SDK, which bypasses
firestore.rules entirely, so these checks are the only thing standing between a
request and another student's documents.
"""

from fastapi import Header, HTTPException


def require_uid(authorization: str = Header(None)) -> str:
    """FastAPI dependency: verify ``Authorization: Bearer <id-token>``.

    Raises 401 if the header is missing, malformed, or the token does not
    verify. Fails closed: if firebase_admin was never initialised (no
    credentials on disk, local-DB fallback), verification raises and the
    request is rejected rather than waved through.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        from firebase_admin import auth as firebase_auth

        decoded = firebase_auth.verify_id_token(token)
    except Exception:
        # Covers expired/forged tokens and an uninitialised Admin SDK alike.
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid


def assert_owner(doc: dict, uid: str, what: str = "Resource") -> dict:
    """Return ``doc`` if ``uid`` owns it, else raise.

    A document the caller does not own is reported as 404, not 403: a 403 would
    confirm that the id exists, which lets someone enumerate other users' ids.
    """
    if not doc or doc.get("userId") != uid:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return doc


def owned_only(docs: list, uid: str) -> list:
    """Filter a by-course listing down to the rows the caller owns.

    Course ids are client-supplied, so a listing must never be trusted to
    contain only the caller's rows.
    """
    return [d for d in (docs or []) if d.get("userId") == uid]
