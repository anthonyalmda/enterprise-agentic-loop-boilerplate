"""
Application-level authenticated encryption (AES-256-GCM) with Associated Authenticated Data (AAD).
Binds ciphertext to specific (table, column, row_uuid) coordinates to prevent cross-row/column tampering.
"""
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TextVault:
    def __init__(self, master_key_b64: str, key_version: str = "v1"):
        raw_key = base64.b64decode(master_key_b64)
        if len(raw_key) != 32:
            raise ValueError("Master key must be exactly 32 bytes (256 bits).")
        self._aesgcm = AESGCM(raw_key)
        self._version = key_version

    @staticmethod
    def _build_aad(table: str, column: str, row_uuid: str) -> bytes:
        return f"{table}.{column}:{row_uuid}".encode("utf-8")

    def encrypt(self, plaintext: str, *, table: str, column: str, row_uuid: str) -> str:
        iv = os.urandom(12)
        aad = self._build_aad(table, column, row_uuid)
        ciphertext = self._aesgcm.encrypt(iv, plaintext.encode("utf-8"), aad)
        iv_b64 = base64.b64encode(iv).decode("ascii")
        ct_b64 = base64.b64encode(ciphertext).decode("ascii")
        return f"{self._version}:{iv_b64}:{ct_b64}"

    def decrypt(self, payload: str, *, table: str, column: str, row_uuid: str) -> str:
        version, iv_b64, ct_b64 = payload.split(":", maxsplit=2)
        if version != self._version:
            raise ValueError(f"Unsupported key version: {version}")
        iv = base64.b64decode(iv_b64)
        ciphertext = base64.b64decode(ct_b64)
        aad = self._build_aad(table, column, row_uuid)
        # Raises InvalidTag immediately if moved to another row, column, or table
        plaintext_bytes = self._aesgcm.decrypt(iv, ciphertext, aad)
        return plaintext_bytes.decode("utf-8")