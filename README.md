# CryptoSplit

CryptoSplit implements the system flow in the architecture slide: owner upload → fragmentation → per-fragment encryption → cloud/object storage → authorized retrieval → verification/decryption → ordered reconstruction.

The cryptography in the slide is adjusted to a sound hybrid design: AES-256-GCM encrypts each fragment; RSA-OAEP/SHA-256 wraps only the random AES key for that file. DES is omitted because it is obsolete. Splitting a file does not by itself make it confidential or resilient to loss.

## System parts

- **Web client:** static browser page served by the API; supports register/login, upload, list, download, delete.
- **API and identity:** FastAPI, Argon2 password hashes, short-lived JWT bearer tokens, ownership and organization-share checks on file retrieval.
- **File workflow:** size validation, UUID identity, chunking, encryption, metadata persistence, retrieval verification, decryption, reconstruction.
- **Cryptography:** fresh AES-256 DEK for each file, fresh 96-bit GCM nonce per fragment, RSA-3072 OAEP/SHA-256 wraps the DEK.
- **Metadata:** MySQL stores users, file metadata, wrapped key, fragment order/nonces/digests.
- **Storage:** local encrypted volume by default; S3-compatible object adapter included. MinIO provides a local S3-compatible option.

For architecture and request flow see [ARCHITECTURE.md](ARCHITECTURE.md). Security constraints and production gaps are listed in [SECURITY.md](SECURITY.md).

## Run using Docker Compose

Requirements: Docker Desktop or Docker Engine with Compose, OpenSSL, and a browser.

1. Copy `.env.example` to `.env` and replace every placeholder. Use hex secrets so the database URL has no escaping issues:

   ```sh
   cp .env.example .env
   openssl rand -hex 32
   ```

   Paste separate `openssl rand -hex 32` results into `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, `JWT_SECRET`, `S3_SECRET_KEY`, and `MINIO_ROOT_PASSWORD`. Set `S3_ACCESS_KEY` to the same value as `MINIO_ROOT_USER` for local MinIO mode. Do not reuse these values outside your local demo.

2. Generate the RSA keypair:

   ```sh
   ./scripts/generate_keys.sh
   ```

   The private key stays in `secrets/` on the host, is mounted read-only, copied to container tmpfs at startup, and read by the unprivileged API process. Keep a protected backup; losing the private key makes existing files unrecoverable.

3. Start the API and MySQL:

   ```sh
   docker compose up --build
   ```

4. Visit **http://127.0.0.1:8000** for the browser UI or **http://127.0.0.1:8000/docs** for the API explorer.

Compose binds the API to loopback for local use. Do not expose this HTTP endpoint directly to the internet.

### Use MinIO as local cloud storage

The default mode writes ciphertext to a Docker volume. To try the S3 adapter:

1. Set `STORAGE_BACKEND=s3` in `.env` and confirm `S3_ENDPOINT_URL=http://minio:9000`, `S3_ACCESS_KEY` equals `MINIO_ROOT_USER`, and `S3_SECRET_KEY` equals `MINIO_ROOT_PASSWORD`.
2. Start the profile:

   ```sh
   docker compose --profile cloud up --build
   ```

MinIO's console is at http://127.0.0.1:9001. The API creates the configured bucket on startup. For real cloud deployment, set the endpoint URL empty for AWS S3, use a dedicated bucket and least-privilege IAM identity, enable provider-managed bucket encryption, private networking, TLS, and a managed key service. Do not use MinIO root credentials in a deployed system.

The API supports AWS KMS wrapping for new file keys: set `KEY_ENCRYPTION_BACKEND=kms`, provide the asymmetric RSA KMS key ARN in `KMS_KEY_ID`, and grant the workload IAM role only the needed KMS and S3 actions. AWS workloads should use task-role credentials instead of static S3 access keys. See [DEPLOYMENT.md](DEPLOYMENT.md) before moving existing files: legacy file keys must be rewrapped and storage/database data migrated before the laptop RSA key can be removed.

## How to use

Register with an email, a unique username, and a password of at least 12 characters. Sign in using either email or username. Existing accounts can set a username in the account section after signing in. Choose a file (default maximum 50 MiB) and upload. The file list shows size and fragment count. Download reconstructs the original only after every fragment passes integrity and authentication checks.

To share with a colleague, first have them register and set a username. Create an organization workspace, then add their username as a member. In **Your files**, choose **Share** on the file and enter that username. They sign in to their own account and find it under **Files shared with me** in the workspace section. Downloads check the signed-in account, active membership, and share grant; a username by itself never grants access. Sharing is download-only. A personal file becomes associated with the workspace when it is first shared there. Deleting the file removes its fragments and share grants.

The API endpoints include `POST /organizations`, `GET /organizations`, `POST /organizations/{id}/members`, `POST /organizations/{id}/files/{file_id}/share`, `GET /organizations/{id}/shared-with-me`, and `DELETE /organizations/{id}/shares/{share_id}`, in addition to auth/file routes. Login returns a bearer token. Swagger's **Authorize** dialog accepts the token.

## Code layout

```text
app/
  main.py          API endpoints and workflow orchestration
  organizations.py organization membership and file sharing routes
  security.py      Argon2, JWT, current-user dependency
  crypto.py        AES-GCM and RSA-OAEP primitives
  storage.py       local and S3-compatible storage adapters
  models.py        SQLAlchemy metadata models
  db.py            database connection/session and additive demo migration
  config.py        environment configuration
  static/          browser UI
scripts/
  generate_keys.sh
compose.yaml       MySQL, API, optional MinIO profile
Dockerfile
requirements.txt
ARCHITECTURE.md
SECURITY.md
```

## Design limits

This implementation is a complete academic demo setup, not a production security certification. Upload and download buffers are bounded by the configured 50 MiB limit. For larger files, implement streaming encryption and multipart object storage. For production add TLS ingress, managed KMS/HSM key custody and key-version rotation, database migrations, rate limits and account recovery, audit logging, malware scanning, quotas, alerting, backups and tested restoration. Use multiple storage providers only with an explicit fault model and redundancy/erasure coding; this baseline requires all fragments and stores them in one backend.
