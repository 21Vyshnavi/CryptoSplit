#!/bin/sh
set -eu
if [ "${KEY_ENCRYPTION_BACKEND:-rsa}" = "kms" ] && [ "${STORAGE_BACKEND:-local}" = "s3" ]; then
  exec gosu 10001:10001 uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi
# Copy host-mounted keys into ephemeral storage with app-only permissions, then drop root.
install -d -o 10001 -g 10001 -m 0700 /run/cryptosplit-keys
install -o 10001 -g 10001 -m 0600 /input-secrets/rsa_private.pem /run/cryptosplit-keys/rsa_private.pem
install -o 10001 -g 10001 -m 0644 /input-secrets/rsa_public.pem /run/cryptosplit-keys/rsa_public.pem
chown -R 10001:10001 /var/lib/cryptosplit/fragments
exec gosu 10001:10001 uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
