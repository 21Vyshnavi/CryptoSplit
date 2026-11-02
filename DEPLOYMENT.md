# Public deployment checklist

## Railway deployment

The Compose file is intended for local Docker use; deploy only the `api` Dockerfile as a Railway service, with Railway MySQL and a private Railway Storage Bucket as separate services. In the API service set `DATABASE_URL` to the Railway MySQL service's `MYSQL_URL` reference, set `STORAGE_BACKEND=s3`, and reference the bucket's `BUCKET`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`, and `SECRET_ACCESS_KEY` variables as `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY`, and `S3_SECRET_KEY`. Set `JWT_SECRET` to a new random value, `KEY_ENCRYPTION_BACKEND=rsa`, and provide `RSA_PRIVATE_KEY_B64` and `RSA_PUBLIC_KEY_B64` as base64-encoded PEMs through Railway's secret variables. Do not use local `.env` values as production secrets. The app's RSA loaders support these base64 values so no laptop key-file mount is needed.

From this directory, deploy the API with Railway CLI (`railway up`) after linking the API service. Railway does not expose a service publicly automatically; generate a domain in the API service's Settings → Networking after the deployment is healthy. Configure `PORT` to `8000` if Railway does not detect the container's exposed port. The existing local MySQL database and fragment volume are not copied by this process; begin with an empty cloud database and bucket unless you intentionally plan and verify a migration.

The current Compose setup is for local development. Its port is bound to `127.0.0.1`, its default fragment store is a local Docker volume, and its RSA key is a file mounted from the laptop. That makes it private to this machine and not a durable public service.

## Public architecture

For a simple AWS first deployment, use an Amazon ECR image with AWS App Runner, a managed MySQL-compatible database reachable only through a VPC connector, a private S3 bucket, AWS KMS for wrapping file keys, and Secrets Manager for the database password and JWT secret. App Runner allocates a public service domain and sets up TLS, so a custom domain can be added later. AWS docs note that a VPC-connected App Runner service routes outbound traffic through that VPC; configure NAT or the required VPC endpoints to reach AWS services. The browser connects to the HTTPS endpoint; the app checks the authenticated account, organization membership, and a specific file-share grant before returning a file. A username or file ID alone never grants access.

## Before opening registration to the public

- Create an asymmetric `RSA_3072` KMS key with `ENCRYPT_DECRYPT` usage and `RSAES_OAEP_SHA_256` for the app's file-key wrapping. The app stores the exact KMS key ARN with each wrapped file key so key rotations do not strand those files.
- Put database credentials, JWT secret, and object-store credentials in the host's secret manager. Do not upload `.env`, RSA private keys, or credentials to Git, an image, or a public bucket.
- Use a private database endpoint, least-privilege object-store identity, a private bucket, TLS, and a restrictive firewall. Expose only the HTTPS web entry point.
- Add email verification, password reset, sign-up abuse protection/rate limiting, account and storage quotas, audit events, monitoring, and tested database/object backups before accepting public users. These product controls are not yet implemented in this demo.
- Run schema migrations as a controlled deployment step; the current startup `create_all` and additive changes are convenient for the demo, not a managed production migration process.
- Test that a user without a grant receives no file bytes, that revoking a grant blocks the next download, and that restoring backups recovers both metadata and ciphertext.

## Deployment sequence

1. Select a cloud host, database service, object-storage provider, and domain. Create the cloud account and set billing limits.
2. Build and push the container image to ECR, then deploy it to App Runner. Give its instance role least-privilege S3 and KMS access. Supply production secrets through Secrets Manager, set `KEY_ENCRYPTION_BACKEND=kms` and `KMS_KEY_ID`, and configure `STORAGE_BACKEND=s3`, the bucket name, and AWS region. Leave S3 static access keys empty so the SDK uses the workload role.
3. Create the managed database with private connectivity, apply reviewed schema migrations, and configure automated encrypted backups.
4. Point the domain's DNS records at the cloud HTTPS entry point. Enable and verify TLS and HTTP-to-HTTPS redirection.
5. Create an initial account and organization, register a second account with a distinct username, add that username to the organization, share one test file, and verify download as the recipient. Verify that a third, unshared account cannot download it.
6. Confirm monitoring, quotas, key recovery, and backup restoration before sharing the public URL.

Keep public launch separate from development: do not make the laptop's port public or use the local `.env` as a production secret store.

## AWS account access

The AWS CLI is installed on the development laptop but it currently has no authenticated AWS account. Sign in locally with AWS IAM Identity Center using `aws configure sso --profile cryptosplit` followed by `aws sso login --profile cryptosplit`; do not paste AWS access keys or passwords into chat. Then select the intended profile and region. App Runner, RDS, networking, S3, KMS, and related resources create billable AWS usage, so choose a region and budget before provisioning.

AWS references: [App Runner service setup and public default domain](https://docs.aws.amazon.com/apprunner/latest/dg/manage-create.html), [App Runner TLS](https://docs.aws.amazon.com/apprunner/latest/dg/security-data-protection-encryption.html), [App Runner VPC outbound traffic](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html), [App Runner Secrets Manager variables](https://docs.aws.amazon.com/apprunner/latest/dg/env-variable-manage.html), and [KMS asymmetric encryption limits and algorithms](https://docs.aws.amazon.com/kms/latest/APIReference/API_Encrypt.html).

## Existing local files

The current laptop database has file records protected by the existing local RSA key, and the fragments live in a Docker volume. Do not deploy a copy of that metadata before rewrapping every file key under KMS and copying both database data and encrypted fragments. Keep offline backups of the original RSA private key, database, and fragment data until a cloud restore works. New AWS uploads use KMS; legacy files with no recorded KMS key ID still need a data migration plan.
