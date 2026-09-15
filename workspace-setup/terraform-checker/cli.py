#!/usr/bin/env python3
"""
CLI entry point for Databricks Terraform Pre-Check.

This module provides a Click-based CLI with shell completion support.
"""

import click
import os
import sys


def get_version() -> str:
    """Get version from VERSION file."""
    try:
        version_file = os.path.join(os.path.dirname(__file__), "VERSION")
        with open(version_file) as f:
            return f.read().strip()
    except Exception:
        return "1.0.0"


# Shell completion scripts
BASH_COMPLETION = '''
_dbx_precheck_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    opts="--cloud --all --region --output --profile --subscription-id --resource-group --project --credentials-file --verbose --dry-run --verify-only --cleanup-orphans --json --log-level --log-file --config --quiet --version --help"
    
    case "${prev}" in
        --cloud|-c)
            COMPREPLY=( $(compgen -W "aws azure gcp" -- ${cur}) )
            return 0
            ;;
        --log-level)
            COMPREPLY=( $(compgen -W "debug info warning error" -- ${cur}) )
            return 0
            ;;
        --output|-o|--log-file|--config|-C|--credentials-file)
            COMPREPLY=( $(compgen -f -- ${cur}) )
            return 0
            ;;
        *)
            ;;
    esac
    
    COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
    return 0
}

complete -F _dbx_precheck_completion dbx-precheck
complete -F _dbx_precheck_completion "python main.py"
'''

ZSH_COMPLETION = '''
#compdef dbx-precheck

_dbx_precheck() {
    local -a opts clouds log_levels
    
    clouds=(aws azure gcp)
    log_levels=(debug info warning error)
    
    _arguments \\
        '(-c --cloud)'{-c,--cloud}'[Cloud provider]:cloud:(${clouds})' \\
        '(-a --all)'{-a,--all}'[Check all clouds]' \\
        '(-r --region)'{-r,--region}'[Cloud region]:region:' \\
        '(-o --output)'{-o,--output}'[Output file]:file:_files' \\
        '--profile[AWS profile]:profile:' \\
        '--subscription-id[Azure subscription]:subscription:' \\
        '--resource-group[Azure resource group]:rg:' \\
        '--project[GCP project]:project:' \\
        '--credentials-file[GCP credentials]:file:_files -g "*.json"' \\
        '(-v --verbose)'{-v,--verbose}'[Verbose output]' \\
        '--dry-run[Dry run mode]' \\
        '--verify-only[Read-only checks without resource creation]' \\
        '--cleanup-orphans[Cleanup orphaned resources]' \\
        '--json[JSON output]' \\
        '--log-level[Log level]:level:(${log_levels})' \\
        '--log-file[Log file]:file:_files' \\
        '(-C --config)'{-C,--config}'[Config file]:file:_files -g "*.yaml"' \\
        '(-q --quiet)'{-q,--quiet}'[Quiet mode]' \\
        '--version[Show version]' \\
        '(-h --help)'{-h,--help}'[Show help]'
}

_dbx_precheck "$@"
'''


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=get_version(), prog_name="Databricks Terraform Pre-Check")
def cli(ctx):
    """
    Databricks Terraform Pre-Check Tool
    
    Validates credentials, permissions, and resources BEFORE running Terraform.
    
    Run 'dbx-precheck check' to start permission validation.
    """
    if ctx.invoked_subcommand is None:
        # Default to running the main check command
        from main import main
        ctx.invoke(main)


@cli.command()
@click.option("--shell", type=click.Choice(["bash", "zsh"]), required=True,
              help="Shell type for completion script")
def completion(shell: str):
    """Generate shell completion script."""
    if shell == "bash":
        click.echo(BASH_COMPLETION)
        click.echo("\n# Add to ~/.bashrc:")
        click.echo("# eval \"$(dbx-precheck completion --shell bash)\"")
    elif shell == "zsh":
        click.echo(ZSH_COMPLETION)
        click.echo("\n# Add to ~/.zshrc:")
        click.echo("# eval \"$(dbx-precheck completion --shell zsh)\"")


@cli.command()
def init_config():
    """Generate a sample configuration file."""
    from utils import generate_sample_config
    
    config_path = "precheck.yaml"
    
    if os.path.exists(config_path):
        if not click.confirm(f"{config_path} already exists. Overwrite?"):
            click.echo("Aborted.")
            return
    
    content = generate_sample_config()
    with open(config_path, "w") as f:
        f.write(content)
    
    click.echo(click.style(f"✓ Configuration file created: {config_path}", fg="green"))
    click.echo("\nEdit this file to customize your settings, then run:")
    click.echo(f"  python main.py --config {config_path}")


@cli.command()
@click.option("--cloud", type=click.Choice(["aws", "azure", "gcp"]),
              help="Validate specific cloud config")
def validate_config(cloud: str):
    """Validate permission YAML configuration files."""
    from pathlib import Path
    from config import validate_all_configs
    
    config_dir = Path(__file__).parent / "config" / "permissions"
    
    click.echo("Validating permission configuration files...")
    click.echo()
    
    results = validate_all_configs(config_dir)
    
    has_errors = False
    for cloud_name, result in results.items():
        if cloud and cloud_name != cloud:
            continue
            
        if result.valid:
            click.echo(click.style(f"✓ {cloud_name.upper()}: Valid", fg="green"))
            for warning in result.warnings:
                click.echo(click.style(f"  ⚠ {warning}", fg="yellow"))
        else:
            click.echo(click.style(f"✗ {cloud_name.upper()}: Invalid", fg="red"))
            for error in result.errors:
                click.echo(click.style(f"  ✗ {error}", fg="red"))
            has_errors = True
    
    click.echo()
    if has_errors:
        click.echo(click.style("Some configurations are invalid. Please fix the errors above.", fg="red"))
        sys.exit(1)
    else:
        click.echo(click.style("All configurations are valid!", fg="green"))


@cli.command()
def doctor():
    """Check system dependencies and credentials."""
    click.echo("Checking system dependencies...")
    click.echo()
    
    # Check Python version
    py_version = sys.version_info
    if py_version >= (3, 10):
        click.echo(click.style(f"✓ Python {py_version.major}.{py_version.minor}.{py_version.micro}", fg="green"))
    else:
        click.echo(click.style(f"✗ Python {py_version.major}.{py_version.minor} (requires 3.10+)", fg="red"))
    
    # Check AWS SDK
    try:
        import boto3
        click.echo(click.style(f"✓ boto3 {boto3.__version__}", fg="green"))
    except ImportError:
        click.echo(click.style("✗ boto3 not installed (pip install boto3)", fg="yellow"))
    
    # Check Azure SDK
    try:
        from azure.identity import DefaultAzureCredential
        click.echo(click.style("✓ azure-identity installed", fg="green"))
    except ImportError:
        click.echo(click.style("✗ azure-identity not installed", fg="yellow"))
    
    # Check GCP SDK
    try:
        from google.cloud import storage
        click.echo(click.style("✓ google-cloud-storage installed", fg="green"))
    except ImportError:
        click.echo(click.style("✗ google-cloud-storage not installed", fg="yellow"))
    
    click.echo()
    click.echo("Checking credentials...")
    click.echo()
    
    from utils import CredentialLoader
    available = CredentialLoader.detect_available_clouds()
    
    for cloud, detected in available.items():
        if detected:
            click.echo(click.style(f"✓ {cloud.upper()} credentials detected", fg="green"))
        else:
            click.echo(click.style(f"✗ {cloud.upper()} credentials not found", fg="yellow"))
    
    click.echo()
    click.echo("Run 'python main.py --cloud <cloud>' to start checking.")


if __name__ == "__main__":
    cli()

