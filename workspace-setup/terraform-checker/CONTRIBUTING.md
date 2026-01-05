# Contributing to Databricks Terraform Pre-Check

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Updating Permissions](#updating-permissions)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)

## Code of Conduct

Be respectful and inclusive. We welcome contributions from everyone.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a new branch for your changes

## Development Setup

### Prerequisites

- Python 3.10+
- pip or poetry

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/terraform-precheck.git
cd terraform-precheck

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies (including dev)
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=checkers --cov=utils --cov=reporters --cov-report=html

# Run specific test file
pytest tests/test_permission_loader.py -v
```

### Code Quality

```bash
# Format code
black .

# Lint code
ruff check .

# Type check
mypy checkers utils reporters config --ignore-missing-imports
```

## Making Changes

### Branching Strategy

- `main` - Production-ready code
- `develop` - Integration branch for features
- `feature/*` - New features
- `bugfix/*` - Bug fixes
- `docs/*` - Documentation updates

### Commit Messages

Use conventional commits:

```
feat: add new Azure NSG permission check
fix: correct quota calculation for VPCs
docs: update README with new examples
test: add tests for permission loader
refactor: simplify error handling logic
```

## Updating Permissions

This is one of the most common contributions. Permission definitions are in YAML files, making them easy to update.

### Permission Files

```
config/permissions/
├── aws.yaml    # AWS IAM actions
├── azure.yaml  # Azure RBAC permissions
└── gcp.yaml    # GCP IAM permissions
```

### Adding a New Permission

1. Open the appropriate YAML file
2. Find the relevant resource section
3. Add the new action

**Example: Adding a new AWS action**

```yaml
# config/permissions/aws.yaml
resources:
  s3_root_bucket:
    name: "S3 Root Bucket (DBFS)"
    terraform_type: "aws_s3_bucket"
    description: "S3 bucket for DBFS root storage"
    actions:
      - s3:CreateBucket
      - s3:DeleteBucket
      - s3:NewAction  # <-- Add new action here
```

### Adding a New Resource

```yaml
resources:
  new_resource:
    name: "Human-Readable Name"
    terraform_type: "aws_resource_type"
    description: "What this resource does"
    deployment_modes: ["standard", "privatelink"]  # When it's needed
    actions:
      - service:Action1
      - service:Action2
```

### Validation

After updating permissions, validate the YAML:

```bash
python -c "
from config.schema import validate_all_configs
from pathlib import Path
results = validate_all_configs(Path('config/permissions'))
for cloud, result in results.items():
    print(f'{cloud}: {\"Valid\" if result.valid else \"INVALID\"}')"
```

## Testing

### Test Structure

```
tests/
├── test_config_loader.py      # Config file tests
├── test_error_handlers.py     # Error handling tests
├── test_permission_loader.py  # YAML loading tests
├── test_reporters.py          # Output formatting tests
└── test_schema_validation.py  # Schema validation tests
```

### Writing Tests

Use pytest fixtures for common setup:

```python
import pytest
from checkers.base import CheckResult, CheckStatus

class TestMyFeature:
    @pytest.fixture
    def sample_data(self):
        return {"key": "value"}
    
    def test_something(self, sample_data):
        assert sample_data["key"] == "value"
```

### Test Markers

```python
@pytest.mark.integration  # Requires real credentials
@pytest.mark.slow         # Takes > 5 seconds
```

Run specific markers:
```bash
pytest -m "not integration"  # Skip integration tests
```

## Pull Request Process

### Before Submitting

1. ✅ Tests pass: `pytest tests/ -v`
2. ✅ Linting passes: `ruff check .`
3. ✅ Formatting is correct: `black --check .`
4. ✅ Types check: `mypy checkers utils reporters config`
5. ✅ YAML is valid: Run schema validation
6. ✅ Documentation updated (if needed)

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Permission update
- [ ] Documentation

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] YAML validated (if applicable)
- [ ] No breaking changes (or documented)
```

### Review Process

1. Open PR against `develop` (or `main` for hotfixes)
2. CI checks must pass
3. At least one approval required
4. Squash and merge

## Questions?

Open an issue with the `question` label.

---

Thank you for contributing! 🎉

