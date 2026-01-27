"""Tests for general workflow configuration and consistency."""

from pathlib import Path
import re
from typing import Any
import warnings

import pytest
import yaml


class TestWorkflowStructure:
    """Test basic workflow structure and metadata."""

    @pytest.mark.workflows
    def test_all_workflows_have_names(
        self, all_workflows: dict[str, dict[str, Any]]
    ) -> None:
        """All workflows must have descriptive names."""
        for filename, workflow in all_workflows.items():
            assert "name" in workflow, f"{filename} missing name"
            assert workflow["name"].strip(), f"{filename} has empty name"
            assert len(workflow["name"]) > 3, (
                f"{filename} name too short: '{workflow['name']}'"
            )

    @pytest.mark.workflows
    def test_all_workflows_have_valid_triggers(
        self, all_workflows: dict[str, dict[str, object]]
    ) -> None:
        """All workflows must have valid trigger conditions."""
        for filename, workflow in all_workflows.items():
            assert "on" in workflow, f"{filename} missing trigger conditions"

            # Check for common trigger types
            triggers = workflow["on"]
            if isinstance(triggers, dict):
                valid_triggers = {
                    "push",
                    "pull_request",
                    "workflow_dispatch",
                    "workflow_call",
                    "schedule",
                    "release",
                    "issues",
                    "issue_comment",
                }
                for trigger in triggers:
                    assert trigger in valid_triggers, (
                        f"{filename} has invalid trigger: {trigger}"
                    )

    @pytest.mark.workflows
    def test_workflow_jobs_exist(
        self, all_workflows: dict[str, dict[str, Any]]
    ) -> None:
        """All workflows must define at least one job."""
        for filename, workflow in all_workflows.items():
            assert "jobs" in workflow, f"{filename} missing jobs section"
            assert workflow["jobs"], f"{filename} has empty jobs section"


class TestEnvironmentConsistency:
    """Test consistency across workflows for environment settings."""

    @pytest.mark.workflows
    def test_python_versions_consistent(self, pyproject_python_version: str) -> None:
        """All workflows should use the same Python version as pyproject.toml."""
        workflows_to_check = [
            Path(".github/workflows/ci.yml"),
            Path(".github/workflows/release.yml"),
            Path(".github/workflows/reusable-checks.yml"),
        ]

        for workflow_path in workflows_to_check:
            if not workflow_path.exists():
                continue

            with workflow_path.open() as f:
                workflow = yaml.safe_load(f)

            # Check for Python version references in the workflow
            workflow_str = yaml.dump(workflow)
            if "python-version" in workflow_str:
                # Extract python-version values and verify they match
                self._check_python_versions_in_workflow(
                    workflow, pyproject_python_version, workflow_path
                )

    def _check_python_versions_in_workflow(
        self, workflow: dict[str, Any], expected_version: str, workflow_path: Path
    ) -> None:
        """Recursively check Python versions in workflow structure."""

        def find_python_versions(obj: Any, path: str) -> list[tuple[str, str]]:
            versions = []
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "python-version":
                        versions.append((f"{path}.{key}", value))
                    else:
                        versions.extend(find_python_versions(value, f"{path}.{key}"))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    versions.extend(find_python_versions(item, f"{path}[{i}]"))
            return versions

        python_versions = find_python_versions(workflow, str(workflow_path))
        for location, version in python_versions:
            # Handle both string and matrix formats
            if isinstance(version, str) and not version.startswith("${{"):
                # Ignore dynamic versions used in reusable workflows
                assert version == expected_version, (
                    f"{location}: Expected {expected_version}, got {version}"
                )

    @pytest.mark.workflows
    def test_ubuntu_runners_consistent(self) -> None:
        """All workflows should use the same Ubuntu runner version."""
        expected_runner = "ubuntu-latest"
        workflows_to_check = [
            Path(".github/workflows/ci.yml"),
            Path(".github/workflows/release.yml"),
            Path(".github/workflows/reusable-checks.yml"),
        ]

        for workflow_path in workflows_to_check:
            if not workflow_path.exists():
                continue

            with workflow_path.open() as f:
                workflow = yaml.safe_load(f)

            for job_name, job in workflow.get("jobs", {}).items():
                if "runs-on" in job:
                    assert job["runs-on"] == expected_runner, (
                        f"{workflow_path}:{job_name} uses {job['runs-on']}, expected {expected_runner}"
                    )

    @pytest.mark.workflows
    def test_uv_installation_present(self) -> None:
        """Workflows running checks must install uv."""
        # Enforce uv installation on all relevant workflows
        workflows_to_check = [
            Path(".github/workflows/reusable-checks.yml"),
            Path(".github/workflows/release.yml"),
            Path(".github/workflows/docs-lint.yml"),
            Path(".github/workflows/docs.yml"),
        ]

        for workflow_path in workflows_to_check:
            if not workflow_path.exists():
                continue

            with workflow_path.open() as f:
                workflow = yaml.safe_load(f)

            found_uv_setup = False
            for job in workflow.get("jobs", {}).values():
                for step in job.get("steps", []):
                    # Check for the astral-sh/setup-uv action
                    uses = step.get("uses", "")
                    if "astral-sh/setup-uv" in uses:
                        found_uv_setup = True
                        break
                if found_uv_setup:
                    break

            assert found_uv_setup, (
                f"{workflow_path} is missing the 'astral-sh/setup-uv' action. "
                "This is required to ensure 'uv' is available for dependencies and builds."
            )


class TestWorkflowSecurity:
    """Test security best practices in workflows."""

    @pytest.mark.workflows
    def test_no_hardcoded_secrets(self) -> None:
        """Workflows should not contain hardcoded secrets or sensitive data."""
        workflow_dir = Path(".github/workflows")
        suspicious_patterns = [
            "password",
            "secret",
            "token",
            "key",
            "api_key",
            "auth",
            "credential",
            "private",
        ]

        for workflow_file in workflow_dir.glob("*.yml"):
            with workflow_file.open() as f:
                content = f.read().lower()

            for pattern in suspicious_patterns:
                # Allow legitimate uses like ${{ secrets.GITHUB_TOKEN }}
                if pattern in content and "${{ secrets." not in content:
                    # This is a soft check - flag for manual review
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if pattern in line and "${{ secrets." not in line:
                            warnings.warn(
                                f"{workflow_file}:{i} contains '{pattern}' - verify no hardcoded secrets",
                                stacklevel=2,
                            )

    @pytest.mark.workflows
    def test_required_secrets_declared(self) -> None:
        """Steps that use commands requiring secrets must declare them in their env block."""
        workflow_dir = Path(".github/workflows")

        # Define a map of commands that require specific environment variables.
        # The value is the expected environment variable name.
        command_requirements = {
            "semantic-release -v publish": "GH_TOKEN",
            "semantic-release publish": "GH_TOKEN",
        }

        # Map environment variable names to their expected secret sources.
        # This ensures we validate that env vars reference the correct secrets.
        secret_mapping = {
            "GH_TOKEN": "GITHUB_TOKEN",  # semantic-release expects GH_TOKEN but uses GITHUB_TOKEN secret
        }

        for workflow_file in workflow_dir.glob("*.yml"):
            with workflow_file.open() as f:
                workflow = yaml.safe_load(f)

            # Get workflow-level environment
            workflow_env = workflow.get("env", {})

            for job_name, job in workflow.get("jobs", {}).items():
                # Merge workflow and job environments
                job_env = {**workflow_env, **job.get("env", {})}

                for step in job.get("steps", []):
                    if "run" not in step:
                        continue

                    # Merge step env for final scope
                    step_env = {**job_env, **step.get("env", {})}

                    for command, env_var_name in command_requirements.items():
                        if command in step["run"]:
                            # 1. Check if the required environment variable is defined
                            assert env_var_name in step_env, (
                                f"{workflow_file.name} -> {job_name} -> step '{step.get('name')}' "
                                f"uses '{command}' but is missing required env var '{env_var_name}' in env."
                            )

                            # 2. Check if the environment variable references the correct secret
                            expected_secret = secret_mapping.get(
                                env_var_name, env_var_name
                            )
                            expected_value = f"${{{{ secrets.{expected_secret} }}}}"
                            actual_value = step_env.get(env_var_name)
                            assert actual_value == expected_value, (
                                f"{workflow_file.name} -> {job_name} -> step '{step.get('name')}' "
                                f"has env var '{env_var_name}', but its value is incorrect. "
                                f"Expected '{expected_value}', got '{actual_value}'."
                            )

    @pytest.mark.workflows
    def test_permissions_explicitly_defined(self) -> None:
        """Workflows that push changes should have explicit permissions."""
        with Path(".github/workflows/release.yml").open() as f:
            release_workflow = yaml.safe_load(f)

        release_job = release_workflow["jobs"]["release"]
        assert "permissions" in release_job, (
            "Release job must have explicit permissions"
        )

        # PSR action only needs contents permission
        required_permissions = ["contents"]
        permissions = release_job["permissions"]

        for perm in required_permissions:
            assert perm in permissions, f"Release job missing {perm} permission"


class TestMakefileIntegration:
    """Test that workflows properly integrate with Makefile commands."""

    @pytest.mark.workflows
    def test_workflows_use_existing_makefile_targets(
        self, makefile_targets: set[str]
    ) -> None:
        """Workflows should only reference Makefile targets that exist."""
        workflows_to_check = [
            Path(".github/workflows/ci.yml"),
            Path(".github/workflows/release.yml"),
            Path(".github/workflows/reusable-checks.yml"),
        ]

        for workflow_path in workflows_to_check:
            if not workflow_path.exists():
                continue

            with workflow_path.open() as f:
                content = f.read()

            # Look for 'make' commands
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "make " in line and not line.strip().startswith("#"):
                    make_commands = re.findall(r"make\s+([a-zA-Z0-9_-]+)", line)
                    for target in make_commands:
                        assert target in makefile_targets, (
                            f"{workflow_path}:{i} references non-existent make target: {target}"
                        )
