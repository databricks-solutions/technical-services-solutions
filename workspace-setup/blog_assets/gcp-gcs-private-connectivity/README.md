# Blog assets — Databricks on Google Cloud: private connectivity to Cloud Storage

Implementation guides (PDF) and images for the Databricks Community technical blog post
**"Databricks on Google Cloud: private connectivity to Cloud Storage"**.

## Blog post

📝 **Read the blog:** coming soon. The link will be added here once the post is published.

## Implementation guides

Each guide covers one method, step by step, with screenshots from a lab environment.

| Guide | What it covers |
|---|---|
| [Prerequisite: register the GCS bucket in Unity Catalog](./01-unity-catalog-prerequisite.pdf) | Bucket, storage credential, IAM roles and external location. Needed by every method. |
| [Serverless compute: private endpoint to Cloud Storage (NCC, Beta)](./02-serverless-ncc-private-endpoint.pdf) | NCC private endpoint rule for Cloud Storage, perimeter ingress rule and workspace attachment. |
| [Classic compute, option 1: Cloud NAT](./03-classic-cloud-nat.pdf) | The default classic setup and how Google API traffic bypasses NAT. |
| [Classic compute, option 2: Private Google Access with the restricted VIP](./04-classic-restricted-vip.pdf) | Private DNS zone, routes and egress firewall rules for `restricted.googleapis.com`. |
| [Classic compute, option 3: PSC endpoint for Google APIs](./05-classic-psc-endpoint.pdf) | Private Service Connect endpoint with the `vpc-sc` bundle and the DNS record for Cloud Storage. |
| [Lock it down: VPC Service Controls around the bucket](./06-vpc-service-controls.pdf) | Data-only perimeter, dry run, ingress rules for classic, control plane and serverless, and enforcement. |

## Images

The `blog-*.png` files are the diagrams and screenshots embedded in the blog post.

---

**Databricks support doesn't cover this content.** It is provided as-is for guidance and educational purposes. For questions or problems, open a GitHub issue; the maintainers help on a best-effort basis.
