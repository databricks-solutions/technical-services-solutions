# Pull Request

## GitHub Release — new solutions

If this PR adds a **new downloadable solution**, add a row to [`.github/releases.yml`](.github/releases.yml) in the **same PR**. The release workflow only publishes slugs listed in that file. Updates to an already-listed folder do not need a new row.

```yaml
- slug: my-solution-name
  name: "My Solution Name"
  kind: "Agent skill"
  path: "category/path/to/my-solution-name"
```

`slug` becomes the tag `my-solution-name-latest` and the zip `my-solution-name.zip`. `path` is the folder that goes in the zip. `kind` is a short label (for example Agent skill, Terraform, Databricks notebook).

- [ ] New downloadable solution — I added a `releases.yml` row like the example above
- [ ] Not a new solution (docs, fix, or update to an existing listed path)

## Description
Brief description of what this PR does and why.

## Category
- [ ] core-platform
- [ ] data-engineering
- [ ] data-governance
- [ ] data-warehousing  
- [ ] genai-ml
- [ ] launch-accelerator
- [ ] workspace-setup

## Type of Change
- [ ] New project
- [ ] Bug fix
- [ ] Enhancement
- [ ] Documentation

## Project Details
**Project Name:** 
**Purpose:** 
**Technologies Used:** 

## Testing
- [ ] Code runs without errors
- [ ] Documentation is complete
- [ ] Used only synthetic data

## Security Compliance ✅
- [ ] No customer data, PII, or proprietary information
- [ ] No credentials or access tokens
- [ ] Only synthetic data used
- [ ] Third-party licenses acknowledged

---

**By submitting this PR, I confirm I have followed the [CONTRIBUTING.md](../CONTRIBUTING.md) guidelines and security requirements.**