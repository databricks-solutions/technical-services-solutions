# Contributing Guide

Thank you for your interest in contributing to the Genie Space CI/CD project! This document provides guidelines and best practices for contributing.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)

---

## Getting Started

### Prerequisites

Before contributing, ensure you have:

1. **Databricks CLI** installed and configured
2. **Python 3.8+** installed locally
3. Access to a Databricks workspace for testing
4. Basic understanding of:
   - Databricks Asset Bundles (DABs)
   - Unity Catalog
   - AI/BI Genie spaces

### Forking the Repository

1. Fork this repository to your GitHub account
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/genie-cicd.git
   cd genie-cicd
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/ORIGINAL_OWNER/genie-cicd.git
   ```

---

## Development Setup

### Local Development Environment

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install databricks-sdk requests

# Configure Databricks CLI
databricks configure --token
```

### Testing Configuration

Create a test configuration by copying and modifying `databricks.yml`:

```bash
# Validate your configuration
databricks bundle validate --target dev
```

---

## Project Structure

```
genie-cicd/
├── databricks.yml              # Main bundle configuration
├── README.md                   # Project overview
├── SETUP.md                    # Setup instructions
├── CONTRIBUTING.md             # This file
├── .gitignore                  # Git ignore patterns
├── src/
│   ├── export_genie_definition.py    # Export notebook
│   ├── deploy_genie_space.py         # Deploy notebook
│   └── DOCUMENTATION.md              # Source code docs
└── genie_definition/
    ├── genie_space.json              # Dev export (version controlled)
    └── genie_space_prod.json         # Prod version (auto-generated)
```

### Key Files

| File | Description | When to Modify |
|------|-------------|----------------|
| `databricks.yml` | Bundle configuration | Adding jobs, variables, or targets |
| `src/*.py` | Databricks notebooks | Changing export/deploy logic |
| `src/DOCUMENTATION.md` | Code documentation | After modifying source files |
| `README.md` | Project overview | Adding features or changing usage |
| `SETUP.md` | Setup instructions | Changing setup process |

---

## Making Changes

### Branch Naming Convention

Use descriptive branch names:

```
feature/add-multi-space-support
bugfix/fix-schema-replacement
docs/update-setup-guide
refactor/improve-error-handling
```

### Commit Messages

Follow conventional commit format:

```
type(scope): short description

Longer description if needed.
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(deploy): add support for metric views replacement
fix(export): handle spaces with special characters in title
docs(readme): add troubleshooting section
```

---

## Testing

### Local Testing Checklist

Before submitting changes, test the following:

#### 1. Configuration Validation

```bash
databricks bundle validate --target dev
databricks bundle validate --target prod
```

#### 2. Export Functionality

Test the export notebook:
- [ ] Exports successfully with valid space_id
- [ ] Returns proper error for invalid space_id
- [ ] Creates valid JSON output

#### 3. Deploy Functionality

Test the deploy notebook:
- [ ] Creates new space when space_id is empty
- [ ] Updates existing space when space_id is provided
- [ ] Catalog/schema replacement works correctly
- [ ] Handles backtick-quoted identifiers
- [ ] Handles plain identifiers

#### 4. End-to-End Test

```bash
# Deploy the bundle
databricks bundle deploy --target dev

# Run the full pipeline
databricks bundle run promote_genie_to_prod --target dev
```

### Test Cases for Catalog Replacement

Verify these replacement scenarios work:

| Input | Expected Output |
|-------|-----------------|
| `main_th.schema_dev.table` | `target_cat.target_schema.table` |
| `` `main_th`.`schema_dev`.`table` `` | `` `target_cat`.`target_schema`.`table` `` |
| `SELECT * FROM main_th.schema_dev.t` | `SELECT * FROM target_cat.target_schema.t` |

---

## Code Style

### Python Guidelines

1. **Imports**: Group imports in order: standard library, third-party, local
2. **Docstrings**: Use docstrings for all functions
3. **Type hints**: Include type hints where practical
4. **Comments**: Use clear section headers with `# ========`

### Example Function Style

```python
def replace_catalog_schema(
    text: str,
    source_catalog: str,
    target_catalog: str,
    source_schema: Optional[str] = None,
    target_schema: Optional[str] = None
) -> str:
    """
    Replace catalog and schema names in a text string.
    
    Handles both formats:
    - Without backticks: catalog.schema.table
    - With backticks: `catalog`.`schema`.`table`
    
    Args:
        text: The text to search and replace in
        source_catalog: The catalog name to find
        target_catalog: The catalog name to replace with
        source_schema: Optional schema name to find
        target_schema: Optional schema name to replace with
    
    Returns:
        The text with replacements applied
    """
    # Implementation...
```

### YAML Guidelines (databricks.yml)

1. Use 2-space indentation
2. Include comments for all TODO items
3. Group related variables together
4. Document all parameters

---

## Pull Request Process

### Before Submitting

1. **Update documentation** if you changed functionality
2. **Test your changes** using the checklist above
3. **Update DOCUMENTATION.md** if you modified source code
4. **Rebase on main** to ensure clean history:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

### PR Template

When creating a PR, include:

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactoring

## Testing Done
- [ ] Validated bundle configuration
- [ ] Tested export functionality
- [ ] Tested deploy functionality
- [ ] Tested catalog/schema replacement

## Documentation
- [ ] Updated README.md (if needed)
- [ ] Updated SETUP.md (if needed)
- [ ] Updated src/DOCUMENTATION.md (if needed)
```

### Review Process

1. Submit PR to `main` branch
2. Ensure all checks pass
3. Request review from maintainers
4. Address any feedback
5. Once approved, maintainer will merge

---

## Areas for Contribution

### Good First Issues

- Improve error messages
- Add more examples to documentation
- Add support for additional JSON paths in catalog replacement
- Create unit tests for replacement functions

### Feature Ideas

- Support for multiple catalog/schema mappings
- Dry-run mode for deployment
- Diff preview before deployment
- Support for Genie space permissions management
- GitHub Actions workflow template
- Azure DevOps pipeline template

---

## Questions?

If you have questions about contributing:

1. Check existing documentation
2. Review closed issues and PRs
3. Open a new issue with the `question` label

Thank you for contributing!
