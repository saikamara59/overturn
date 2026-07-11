"""Password hashing (bcrypt) and org-API-key encryption (Fernet)."""
import bcrypt
from cryptography.fernet import Fernet, InvalidToken


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def last4(key: str) -> str:
    return key[-4:]


class KeyVault:
    """Encrypts/decrypts org Anthropic keys with KEY_ENCRYPTION_SECRET."""

    def __init__(self, secret: str) -> None:
        self._fernet = Fernet(secret.encode())

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise ValueError("could not decrypt org API key") from exc
