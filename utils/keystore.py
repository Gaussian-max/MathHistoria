"""安全的密钥存储"""
import keyring
import os
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


class SecureKeyStore:
    """安全的密钥存储管理器"""
    SERVICE_NAME = "MathHistoria"

    def __init__(self):
        self.use_keyring = self._check_keyring_available()

    def _check_keyring_available(self) -> bool:
        try:
            backend = keyring.get_keyring()
            return getattr(backend, "priority", 0) > 0
        except Exception:
            return False

    def save_api_key(self, username: str, api_key: str) -> bool:
        try:
            if self.use_keyring:
                keyring.set_password(self.SERVICE_NAME, username, api_key)
            else:
                self._save_encrypted(username, api_key)
            return True
        except Exception as e:
            print(f"保存密钥失败: {e}")
            return False

    def get_api_key(self, username: str) -> str | None:
        try:
            if self.use_keyring:
                return keyring.get_password(self.SERVICE_NAME, username)
            else:
                return self._load_encrypted(username)
        except Exception as e:
            print(f"读取密钥失败: {e}")
            return None

    def delete_api_key(self, username: str) -> bool:
        try:
            if self.use_keyring:
                keyring.delete_password(self.SERVICE_NAME, username)
            else:
                self._delete_encrypted(username)
            return True
        except Exception:
            return False

    def _get_encryption_key(self) -> bytes:
        import platform
        machine_id = f"{platform.node()}{platform.machine()}".encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'mathhistoria_salt_v1',
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id))
        return key

    def _save_encrypted(self, username: str, api_key: str):
        key = self._get_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(api_key.encode())
        config_dir = Path.home() / ".mathhistoria" / "secure"
        config_dir.mkdir(parents=True, exist_ok=True)
        key_file = config_dir / f"{username}.key"
        key_file.write_bytes(encrypted)
        os.chmod(key_file, 0o600)

    def _load_encrypted(self, username: str) -> str | None:
        config_dir = Path.home() / ".mathhistoria" / "secure"
        key_file = config_dir / f"{username}.key"
        if not key_file.exists():
            return None
        key = self._get_encryption_key()
        f = Fernet(key)
        encrypted = key_file.read_bytes()
        decrypted = f.decrypt(encrypted)
        return decrypted.decode()

    def _delete_encrypted(self, username: str):
        config_dir = Path.home() / ".mathhistoria" / "secure"
        key_file = config_dir / f"{username}.key"
        if key_file.exists():
            key_file.unlink()


keystore = SecureKeyStore()
