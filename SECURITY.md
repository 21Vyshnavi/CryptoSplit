# Security model

## Included

- Argon2 password hashing, short-lived signed bearer tokens, and explicit owner checks for all file routes.
- Fresh 256-bit AES key per file, fresh 96-bit GCM nonce per fragment, authenticated encryption, and associated data binding each fragment to file ID/index/count.
- RSA-3072 OAEP with SHA-256 for wrapping AES keys; the RSA private key is external to the database and image.
- Server-generated storage object keys; digest, ciphertext-size, completeness, GCM-authentication, and reconstructed-size checks before returning a file.
- Strict upload size cap, read-only API container root filesystem, only startup capabilities needed for key permissions and privilege drop, and a non-root API account.

## Boundaries

This demo's server sees plaintext while uploading and downloading, so it is not end-to-end encrypted against the service operator. Local MinIO uses demo credentials. The RSA keypair is a single global wrapping key and has no automated rotation or historical keyring. Metadata can reveal filenames, sizes, owners, and access patterns. All fragments live in one storage system; fragmentation is not replication or erasure coding.

Before production, use TLS, KMS/HSM-based key custody with key versions and a recovery/rotation plan, least-privilege object-store IAM, strict secret management, schema migration review, brute-force controls, audit events, malware scanning, quotas, monitoring, encrypted backups, and tested recovery. Use streaming upload/download and multipart storage for large files. Review HTTP headers and content-type handling for the target client. Do not store real sensitive files in this demo.
