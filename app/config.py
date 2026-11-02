from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./cryptosplit.db"
    # ECS can inject these fields individually from a Secrets Manager JSON secret.
    # SQLAlchemy URL.create safely handles generated passwords containing URL symbols.
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_name: str = "cryptosplit"
    jwt_secret: str = "development-only-change-this-secret-before-running"
    jwt_issuer: str = "cryptosplit"
    jwt_minutes: int = 30
    rsa_private_key_path: str = "./secrets/rsa_private.pem"
    rsa_public_key_path: str = "./secrets/rsa_public.pem"
    rsa_private_key_b64: str = ""
    rsa_public_key_b64: str = ""
    key_encryption_backend: str = "rsa"
    kms_key_id: str | None = None
    storage_root: str = "./storage/fragments"
    max_upload_bytes: int = 50 * 1024 * 1024
    fragment_bytes: int = 1024 * 1024
    storage_backend: str = "local"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "cryptosplit"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
