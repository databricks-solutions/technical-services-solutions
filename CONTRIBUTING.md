# Contributing to Technical Services Solutions

This guide outlines the requirements and processes for contributing code examples, demos, and scripts.

## Contribution Requirements

All contributions are expected to follow these mandatory guidelines:

### Security and Compliance Standards

**CRITICAL REQUIREMENTS - NO EXCEPTIONS:**

- ✅ **No non-public information** - This repo must not contain any customer data, PII, or proprietary information
- ✅ **No credentials** - No access tokens, PATs, passwords, or any authentication credentials
- ✅ **Synthetic data only** - Use only data generated with Faker, dbldatagen tool, or LLAMA-4 (following fine-tuning terms)
- ✅ **Proper licensing** - All 3rd party code/assets must be acknowledged with appropriate license (Apache, BSD, MIT, or DB license)
- ✅ **Peer review mandatory** - All content must be reviewed by at least one team member and/or relevant SME

### Repository Structure

Your contribution must be placed in the appropriate category:

```
Technical-Services-Solutions/
├── Platform/
├── Datawarehousing/
├── ML & GenAI/
├── Data Engineering/
├── Launch Accelerator/
└── Datascience/
```

### Project Standards

**Naming Convention:**
- Use consistent, descriptive project names
- Follow kebab-case format (e.g., `customer-churn-prediction`)
- Names should clearly indicate the project's purpose

**Required Files:**
- **README.md** - Following the repository template
- **.gitignore** - To prevent unnecessary files from being committed
- **requirements.txt** or equivalent dependency file

## Contribution Process

### 1. Create a New Project

All new projects must be submitted via **Pull Request** with:

**PR Description Must Include:**
- Project purpose and functionality
- Target category (Platform, Data Engineering, etc.)
- Technologies and dependencies used
- Expected audience/use case
- Confirm project is functional on databricks

### 2. Project Structure Template

Each project should follow a similar structure to ensure consistency and ease of navigation. While not mandatory to be identical, these guidelines help maintain organization across all projects:

```
your-project-name/
├── README.md
├── .gitignore
├── requirements.txt
├── src/
│   └── [your code files]
├── notebooks/
│   └── [databricks notebooks]
├── data/
│   └── [synthetic sample data only]
└── docs/
    └── [additional documentation]
```

### 3. README Template

Your project README must follow this template:

```markdown
# REPO NAME

Fill here a description at a functional level - what is this content doing

## Video Overview

Include a GIF overview of what your project does. Use a service like Quicktime, Zoom or Loom to create the video, then convert to a GIF.

## Installation

Include details on how to use and install this content. 

## License

&copy; 2025 Databricks, Inc. All rights reserved.
The source in this notebook is provided subject to the Databricks License [https://databricks.com/db-license-source].
All included or referenced third party libraries are subject to the licenses set forth below.

| library                                | description             | license    | source                                              |
|----------------------------------------|-------------------------|------------|-----------------------------------------------------|
```

### 4. Code Review Process

**Review Requirements:**
- **Technical Review** - At least one code reviewer must approve
- **SME Review** - Subject Matter Expert review for domain-specific content

**Review Criteria:**
- Code quality and documentation
- Adherence to security guidelines
- Proper error handling
- Performance considerations
- Reusability and maintainability

## Git Best Practices

### Branching Strategy
- Create feature branches from `main`
- Use descriptive branch names: `feature/category/project-name`
- Example: `feature/data-engineering/real-time-streaming-pipeline`

### Commit Messages
- Use clear, descriptive commit messages
- Start with action verb (Add, Update, Fix, Remove)
- Example: "Add customer segmentation ML pipeline for retail use case"

### .gitignore Requirements
Ensure your `.gitignore` includes:

```
# Databricks
.databricks/
*.dbc

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
pip-log.txt
pip-delete-this-directory.txt
.tox
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.log
.git
.mypy_cache
.pytest_cache
.hypothesis

# Jupyter Notebook
.ipynb_checkpoints

# Credentials (NEVER COMMIT)
*.key
*.pem
*.p12
*.pfx
*config.json
*credentials*
*.env

# OS
.DS_Store
Thumbs.db
```

## Repository Maintenance

### Annual Reviews
- Project owners conduct annual reviews
- Outdated projects should be updated or archived

### Issue Management
- **Technical Issues**: Use GitHub Issues
- **Regional Support**: Contact your Regional SME (AMER, APJ, EMEA)
- **Security Violations**: Immediate escalation to repository owners

## Getting Started

1. **Clone** the repository
2. **Create** a feature branch from main
3. **Develop** your solution following guidelines
4. **Test** thoroughly with synthetic data
5. **Document** using the README template
6. **Submit** a Pull Request with detailed description
7. **Collaborate** with reviewers for approval

## Questions?

For contribution questions or guidance:
- Open a GitHub Discussion
- Contact repository owners
- Reach out to your Regional SME

**Remember**: This is a client-facing repository. All contributions should be well-documented to facilitate users' use.
