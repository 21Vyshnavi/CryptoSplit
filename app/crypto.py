import base64, hashlib, os
import boto3
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from .config import settings

AAD_PREFIX = b"cryptosplit:v1:"

def load_public_key():
    if settings.rsa_public_key_b64:
        pem = base64.b64decode(settings.rsa_public_key_b64, validate=True)
    else:
        with open(settings.rsa_public_key_path, "rb") as f:
            pem = f.read()
    return serialization.load_pem_public_key(pem)

def load_private_key():
    if settings.rsa_private_key_b64:
        pem = base64.b64decode(settings.rsa_private_key_b64, validate=True)
    else:
        with open(settings.rsa_private_key_path, "rb") as f:
            pem = f.read()
    return serialization.load_pem_private_key(pem, password=None)

def wrap_key(key: bytes) -> tuple[bytes, str | None]:
    if settings.key_encryption_backend == "kms":
        if not settings.kms_key_id:
            raise RuntimeError("KMS_KEY_ID is required when KEY_ENCRYPTION_BACKEND=kms")
        response = boto3.client("kms", region_name=settings.s3_region).encrypt(
            KeyId=settings.kms_key_id,
            Plaintext=key,
            EncryptionAlgorithm="RSAES_OAEP_SHA_256",
        )
        return response["CiphertextBlob"], response["KeyId"]
    if settings.key_encryption_backend != "rsa":
        raise RuntimeError("KEY_ENCRYPTION_BACKEND must be rsa or kms")
    return load_public_key().encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)), None

def unwrap_key(wrapped: bytes, key_id: str | None = None) -> bytes:
    if key_id:
        response = boto3.client("kms", region_name=settings.s3_region).decrypt(
            KeyId=key_id,
            CiphertextBlob=wrapped,
            EncryptionAlgorithm="RSAES_OAEP_SHA_256",
        )
        return response["Plaintext"]
    return load_private_key().decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))

def aad(file_id: str, index: int, count: int) -> bytes:
    return AAD_PREFIX + f"{file_id}:{index}:{count}".encode()

def encrypt_fragment(key: bytes, data: bytes, file_id: str, index: int, count: int):
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, data, aad(file_id, index, count))
    return nonce, ciphertext, hashlib.sha256(ciphertext).hexdigest()

def decrypt_fragment(key: bytes, nonce: bytes, ciphertext: bytes, file_id: str, index: int, count: int):
    return AESGCM(key).decrypt(nonce, ciphertext, aad(file_id, index, count))
