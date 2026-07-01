# Databricks Pre-Deployment Check — Quick Start

This is a one-page guide. It checks whether your cloud account has the right
permissions to deploy a Databricks workspace with Terraform, and produces a
**`report.md`** you send back to your Databricks contact. That's the whole job.

You do **not** need to edit any files or change any settings.

---

## Two ways to run it (the runner asks you to pick one)

**1) Dry run — creates nothing.**
Shows exactly what the full run *would* create and test in your account. No
changes are made. Run this first if you (or your security team) want to see what
will happen before anything runs. A dry run does **not** produce a report.

**2) Full run — creates temporary resources, then deletes them.**
This is the real check, and the one that produces the `report.md` you send back.
To *prove* your permissions, it briefly creates a few small, clearly-tagged
resources (named `dbxprecheck-*` / `dbx-precheck-temp-*`) and **deletes them at
the end of the run** (on Azure, deleting the resource group removes everything
inside it):

- On **Azure**, this briefly includes a NAT Gateway + Public IP — a few cents for
  the seconds they exist.
- On **AWS**, it's a temporary bucket / IAM role / security group (no cost).
- On **GCP**, nothing is ever created — it's read-only in *both* modes.

**A typical path:** dry run once to see what it does → full run to produce the report.

---

## Step 1 — Prerequisites

1. **Python 3.10 or newer** installed ([python.org/downloads](https://www.python.org/downloads/)).
2. **Logged in to your cloud** from this machine, using an identity that has
   permission to deploy the workspace:

   | Cloud | Log in with |
   |-------|-------------|
   | AWS   | `aws configure` (or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) |
   | Azure | `az login` |
   | GCP   | `gcloud auth application-default login` |

## Step 2 — Have these ready

You'll be asked for a couple of values — nothing to configure in advance, just
know them:

| Cloud | You'll be asked for |
|-------|---------------------|
| AWS   | Region (e.g. `us-east-1`) |
| Azure | Subscription ID + region (e.g. `eastus`) |
| GCP   | Project ID + region (e.g. `us-central1`) |

## Step 3 — Run it

From this folder:

**macOS / Linux**
```bash
./run.sh
```

**Windows (PowerShell)**
```powershell
.\run.ps1
```
> If Windows blocks the script with *"running scripts is disabled on this system,"*
> run it this way instead (allows it for this one session only):
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\run.ps1
> ```

> **Linux note:** if you get *"No module named venv"*, install the venv package
> first — e.g. `sudo apt install python3-venv` on Debian/Ubuntu — then re-run.

The runner sets everything up on first run (~1–2 minutes), asks for your cloud
and the values above, then asks whether you want a **dry run** or a **full run**.
A full run writes **`report.md`** next to this file.

## Step 4 — Send us the report

Send **`report.md`** back to your Databricks contact. Done.

---

### What the report tells you

At the top you'll see a **Deployment Compatibility** summary — for each workspace
type (Standard, PrivateLink, Unity Catalog, Full) it says one of:

- **SUPPORTED** — every permission that type needs was verified and is clean.
- **NOT SUPPORTED** — a required permission is missing; the report names which one.
- **REVIEW** — permissions are fine, but something is worth a look (e.g. a small subnet).
- **NOT VERIFIED** — the check couldn't confirm this area (e.g. read-only mode).

If anything is missing, the report lists exactly which permission is needed and
how to fix it — just send `report.md` back and we'll take it from there.

---

**Locked-down environment** where you're not allowed to create resources at all,
even temporarily? Run a read-only check instead — it produces a real report but
can't confirm every write permission:
`./run.sh --cloud azure --subscription-id <id> --region <region> --verify-only`

Need more detail, CI/CD integration, or targeted network checks? See the full
[README.md](README.md). Questions? Contact your Databricks team — this tool is
provided as-is and is not covered by Databricks support.
