# Blog assets — Private connectivity from Databricks on AWS to Amazon S3

Images for the Databricks Community technical blog post
**"Private connectivity from Databricks on AWS to Amazon S3"**.

## Blog post

📝 **Read the blog:** _Coming soon — the link will be added here once the post is published on the [Databricks Community Technical Blog](https://community.databricks.com/t5/technical-blog/bg-p/technical-blog)._

<!-- TODO: replace the line above with the published URL, e.g.
**Read the blog:** [Private connectivity from Databricks on AWS to Amazon S3](https://community.databricks.com/t5/technical-blog/...)
-->

## Images

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
