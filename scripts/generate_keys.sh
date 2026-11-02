#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p secrets
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out secrets/rsa_private.pem
openssl pkey -in secrets/rsa_private.pem -pubout -out secrets/rsa_public.pem
chmod 600 secrets/rsa_private.pem
chmod 644 secrets/rsa_public.pem
printf 'RSA-3072 keypair created in ./secrets. Keep rsa_private.pem secret and backed up.\n'
