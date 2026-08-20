#!/usr/bin/env pwsh
#
# Databricks Terraform Pre-Check — one-command runner (Windows / PowerShell).
#
# This does the whole setup for you: it creates a local Python environment,
# installs what it needs, asks two or three questions, runs the check, and
# writes a report.md you can send back to your Databricks contact.
#
#   .\run.ps1                                    # interactive (recommended)
#   .\run.ps1 --cloud aws --region us-east-1     # advanced: pass flags straight through
#
# Requirements: Python 3.10+ and you must already be logged in to your cloud
# CLI (aws configure / az login / gcloud auth application-default login).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- 1. Find a suitable Python (3.10+) -------------------------------------
function Find-Python {
    foreach ($candidate in @("python", "python3", "py")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "ERROR: Python 3.10 or newer is required but was not found." -ForegroundColor Red
    Write-Host "       Install it from https://www.python.org/downloads/ and re-run .\run.ps1"
    exit 1
}

# --- 2. Create / reuse the virtual environment -----------------------------
$venv = "venv"
if (-not (Test-Path $venv)) {
    Write-Host "-> Creating Python virtual environment (one-time setup)..."
    & $python -m venv $venv
}
# venv layout differs by platform: Scripts\ on Windows, bin/ on Unix (pwsh on
# macOS/Linux). Use whichever exists so this runs anywhere PowerShell does.
$activate = Join-Path $venv "Scripts/Activate.ps1"
if (-not (Test-Path $activate)) { $activate = Join-Path $venv "bin/Activate.ps1" }
. $activate

# --- 3. Install dependencies (only when needed) ----------------------------
$marker = Join-Path $venv ".deps-installed"
$needInstall = -not (Test-Path $marker) -or `
    ((Get-Item requirements.txt).LastWriteTime -gt (Get-Item $marker).LastWriteTime)
if ($needInstall) {
    Write-Host "-> Installing dependencies (one-time, ~1-2 min)..."
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

# --- 4. Gather inputs ------------------------------------------------------
if ($args.Count -gt 0) {
    # Advanced mode: forward whatever flags the caller passed, untouched.
    $runArgs = $args
} else {
    Write-Host ""
    $cloud = (Read-Host "Which cloud? aws / azure / gcp").ToLower().Trim()
    $runArgs = @("--cloud", $cloud)

    switch ($cloud) {
        "aws" {
            $region = Read-Host "AWS region (e.g. us-east-1)"
            $runArgs += @("--region", $region)
        }
        "azure" {
            $sub = Read-Host "Azure subscription ID"
            $region = Read-Host "Azure region (e.g. eastus)"
            $runArgs += @("--subscription-id", $sub, "--region", $region)
        }
        "gcp" {
            $project = Read-Host "GCP project ID"
            $region = Read-Host "GCP region (e.g. us-central1)"
            $runArgs += @("--project", $project, "--region", $region)
        }
        default {
            Write-Host "ERROR: unknown cloud '$cloud' (expected aws, azure, or gcp)." -ForegroundColor Red
            exit 1
        }
    }

    Write-Host ""
    Write-Host "How would you like to run the check?"
    Write-Host ""
    Write-Host "  1) Dry run  - Preview only. Shows exactly what the full run WOULD"
    Write-Host "               create and test. NOTHING is created in your account and"
    Write-Host "               no changes are made. Good for a first look."
    Write-Host ""
    Write-Host "  2) Full run - Creates small, clearly-tagged temporary resources"
    Write-Host "               (dbxprecheck-* / dbx-precheck-temp-*), verifies your"
    Write-Host "               permissions, then DELETES them. On Azure this briefly"
    Write-Host "               includes a NAT Gateway + Public IP (a few cents). This is"
    Write-Host "               the real check and produces the report.md you send back."
    Write-Host "               [recommended]"
    Write-Host ""
    Write-Host "  (GCP is always read-only - it never creates anything, in either mode.)"
    Write-Host ""
    $mode = (Read-Host "Choose 1 or 2 (default 2)").Trim()

    if ($mode -eq "1") {
        $runMode = "dryrun"
        $runArgs += "--dry-run"
    } else {
        $runMode = "full"
        # Produce the customer-friendly report file to send back.
        $runArgs += @("--format", "markdown", "--output", "report.md")
    }
}

# --- 5. Run ----------------------------------------------------------------
Write-Host ""
Write-Host "-> Running the pre-check..."
# The tool exits non-zero when it finds blockers; that's expected, so don't let
# it abort the script before we point you at the report.
$ErrorActionPreference = "Continue"
& python main.py @runArgs

Write-Host ""
if ($runMode -eq "dryrun") {
    Write-Host "That was a PREVIEW (dry run) - nothing was created in your account." -ForegroundColor Green
    Write-Host "When you're ready for the real check, run .\run.ps1 again and choose"
    Write-Host "option 2 (Full run). It creates, verifies, and deletes the temporary"
    Write-Host "resources and writes the report.md you send back."
} elseif (Test-Path report.md) {
    Write-Host "Done. Your report is here:" -ForegroundColor Green
    Write-Host "    $(Join-Path (Get-Location) 'report.md')"
    Write-Host ""
    Write-Host "Please send report.md back to your Databricks contact."
} else {
    Write-Host "The run finished but no report.md was produced - check the output above."
}
