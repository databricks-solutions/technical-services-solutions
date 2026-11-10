# Blog assets — Private connectivity from Databricks on AWS to Amazon S3

Images for the Databricks Community technical blog post
**"Private connectivity from Databricks on AWS to Amazon S3"**.

Files are named `<section>-<step>-<what-it-shows>.png`, in reading order:

| Prefix | Blog section |
|---|---|
| `00-shared-` | Screenshot reused in several sections (S3 bucket policy editor) |
| `01-overview-` | Key concepts — architecture overview |
| `02-uc-auth-` | Unity Catalog access to S3 — IAM role, storage credential, external location |
| `03-classic-gateway-` | Classic compute — S3 gateway endpoint |
| `04-classic-interface-` | Classic compute — S3 interface endpoint (PrivateLink) |
| `05-serverless-default-` | Serverless — default path with S3 bucket policy |
| `06-serverless-ncc-` | Serverless — dedicated endpoint (NCC S3 rule) |

The blog embeds them via `https://raw.githubusercontent.com/thaishenrique-git/technical-services-solutions/main/workspace-setup/blog_assets/aws-s3-private-connectivity/<file>.png`.
