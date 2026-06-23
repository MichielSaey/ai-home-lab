import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("MASTER_KEY")
    if not key:
        raise RuntimeError("MASTER_KEY is not set")
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("plaintext is required")
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    if token is None:
        raise ValueError("token is required")
    fernet = _get_fernet()
    return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
