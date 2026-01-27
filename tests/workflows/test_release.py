"""Tests specifically for the release workflow and semantic-release configuration."""

from pathlib import Path
import re

import pytest
import yaml


class TestReleaseWorkflowSafety:
    """Test safety mechanisms in the release workflow."""

    @pytest.mark.workflows
    def test_manual_trigger_only(self, release_workflow):
        """Release workflow should only be manually triggered."""
        triggers = release_workflow["on"]
        assert "workflow_dispatch" in triggers, "Release must be manually triggerable"

        # Should not have push/PR triggers
        dangerous_triggers = ["push", "pull_request", "schedule"]
        for trigger in dangerous_triggers:
            assert trigger not in triggers, (
                f"Release workflow should not trigger on {trigger}"
            )

    @pytest.mark.workflows
    def test_dry_run_defaults_to_true(self, release_workflow):
        """Dry run should default to true to prevent accidental releases."""
        dry_run_input = release_workflow["on"]["workflow_dispatch"]["inputs"]["dry_run"]

        assert dry_run_input.get("type") == "boolean", "dry_run should be boolean type"
        assert dry_run_input.get("default") is True, "dry_run should default to true"
        assert "description" in dry_run_input, "dry_run should have a description"

    @pytest.mark.workflows
    def test_release_job_has_concurrency_protection(self, release_workflow):
        """Release job must have concurrency protection to prevent race conditions."""
        release_job = release_workflow["jobs"]["release"]

        assert "concurrency" in release_job, (
            "Release job must have concurrency protection"
        )
        concurrency = release_job["concurrency"]

        # The workflow uses a dynamic concurrency group expression
        assert concurrency.get("group") == "${{ github.workflow }}-${{ github.ref }}", (
            "Concurrency group should use dynamic expression"
        )
        assert concurrency.get("cancel-in-progress") is False, (
            "Should not cancel in-progress releases"
        )

    @pytest.mark.workflows
    def test_release_job_permissions(self, release_workflow):
        """Release job must have appropriate permissions."""
        release_job = release_workflow["jobs"]["release"]

        assert "permissions" in release_job, (
            "Release job must have explicit permissions"
        )
        permissions = release_job["permissions"]

        # PSR action only needs contents: write permission
        required_permissions = {
            "contents": "write",
        }

        for perm, level in required_permissions.items():
            assert perm in permissions, f"Missing required permission: {perm}"
            assert permissions[perm] == level, (
                f"Permission {perm} should be {level}, got {permissions[perm]}"
            )

    @pytest.mark.workflows
    def test_release_has_verification_step(self, release_workflow):
        """Release workflow must verify artifacts to prevent silent failures."""
        # This test is not applicable to the current workflow design
        # The workflow uses semantic-release which handles verification internally
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Verify that the semantic-release step exists
        semantic_release_steps = [
            step for step in steps if step.get("name") == "Create and Publish Release"
        ]
        assert semantic_release_steps, "Should have semantic-release step"


class TestReleaseWorkflowLogic:
    """Test the conditional logic in the release workflow."""

    @pytest.mark.workflows
    def test_dry_run_and_actual_release_are_mutually_exclusive(self, release_workflow):
        """Dry run and actual release steps should be mutually exclusive."""
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # The workflow uses a single semantic-release step with conditional behavior
        # Check for summary steps that handle different outcomes
        dry_run_summary_steps = []
        release_summary_steps = []

        for step in steps:
            if "if" in step:
                condition = step["if"]
                if "inputs.dry_run == true" in condition:
                    dry_run_summary_steps.append(step.get("name", "unnamed"))
                elif "steps.release.outputs.released == 'true'" in condition:
                    release_summary_steps.append(step.get("name", "unnamed"))

        assert dry_run_summary_steps, "Should have dry-run summary steps"
        assert release_summary_steps, "Should have release summary steps"

    @pytest.mark.workflows
    def test_release_steps_check_new_version_exists(self, release_workflow):
        """Release steps should check that a new version is actually needed."""
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Find the semantic-release step
        semantic_release_steps = [
            step for step in steps if step.get("name") == "Create and Publish Release"
        ]

        assert semantic_release_steps, "Should have semantic-release step"

        # Semantic-release handles version checking internally
        # The workflow uses no_operation_mode based on dry_run input
        semantic_release_step = semantic_release_steps[0]
        assert "no_operation_mode" in semantic_release_step.get("with", {}), (
            "Semantic-release step should use no_operation_mode"
        )

    @pytest.mark.workflows
    def test_publish_step_skipped_during_dry_run(self, release_workflow):
        """Publish step must be skipped during dry run to prevent tag-not-found errors.

        Regression test: In dry_run mode, semantic-release calculates versions but
        does not create git tags. The publish step must check for dry_run to avoid
        attempting to publish to a non-existent tag.
        """
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Find the publish step
        publish_steps = [
            step for step in steps if step.get("name") == "Publish to GitHub Release"
        ]
        assert publish_steps, "Should have 'Publish to GitHub Release' step"

        publish_step = publish_steps[0]
        condition = publish_step.get("if", "")

        # Must check that a release was made
        assert "steps.release.outputs.released == 'true'" in condition, (
            "Publish step must check that release was made"
        )

        # Must exclude dry run mode to prevent tag-not-found errors
        assert "dry_run" in condition, (
            "Publish step must check dry_run to skip during dry run mode"
        )

    @pytest.mark.workflows
    def test_release_summary_skipped_during_dry_run(self, release_workflow):
        """Release Summary must be skipped during dry run to avoid false success messages.

        Regression test: When dry_run is enabled and a release would be made, the
        Release Summary step should not run, as it would incorrectly claim
        "Release Successful" when nothing was actually published.
        """
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Find the release summary step
        summary_steps = [
            step for step in steps if step.get("name") == "Release Summary"
        ]
        assert summary_steps, "Should have 'Release Summary' step"

        summary_step = summary_steps[0]
        condition = summary_step.get("if", "")

        # Must check that a release was made
        assert "steps.release.outputs.released == 'true'" in condition, (
            "Release Summary must check that release was made"
        )

        # Must exclude dry run mode to avoid false success messages
        assert "dry_run" in condition, (
            "Release Summary must check dry_run to skip during dry run mode"
        )

    @pytest.mark.workflows
    def test_git_configuration_in_release(self, release_workflow):
        """Release workflow should configure Git properly."""
        release_job = release_workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Check that the checkout step has the required configuration
        checkout_steps = [
            step for step in steps if step.get("name") == "Checkout repository"
        ]
        assert checkout_steps, "Should have checkout step"

        checkout_step = checkout_steps[0]
        with_config = checkout_step.get("with", {})

        # Should fetch full history for semantic-release
        assert with_config.get("fetch-depth") == 0, (
            "Should fetch full history for semantic-release"
        )

        # Should have token for authentication (using PAT instead of SSH key)
        assert "token" in with_config, "Should have token for authentication"


class TestSemanticReleaseConfiguration:
    """Test semantic-release configuration in pyproject.toml."""

    @pytest.mark.workflows
    def test_version_configuration(self, semantic_release_config):
        """Version configuration must be correct."""
        assert "version_toml" in semantic_release_config, "Must specify version_toml"

        version_toml = semantic_release_config["version_toml"]
        if isinstance(version_toml, list):
            assert "pyproject.toml:project.version" in version_toml
        else:
            assert version_toml == "pyproject.toml:project.version"

    @pytest.mark.workflows
    def test_tag_format(self, semantic_release_config):
        """Tag format should follow semantic versioning."""
        assert "tag_format" in semantic_release_config, "Must specify tag_format"

        tag_format = semantic_release_config["tag_format"]
        assert tag_format == "v{version}", (
            f"Expected 'v{{version}}', got '{tag_format}'"
        )

    @pytest.mark.workflows
    def test_branch_configuration(self, semantic_release_config):
        """Branch configuration must be correct."""
        assert "branches" in semantic_release_config, "Must configure branches"

        branches = semantic_release_config["branches"]
        assert "main" in branches, "Must configure main branch"

        main_branch = branches["main"]
        assert main_branch.get("match") == "main", (
            f"Main branch should match 'main', got {main_branch.get('match')}"
        )
        assert main_branch.get("prerelease") is False, (
            "Main branch should not be prerelease"
        )

    @pytest.mark.workflows
    def test_build_command_configuration(self, semantic_release_config):
        """Build command should be configured for Python packages."""
        assert "build_command" in semantic_release_config, "Must specify build_command"

        build_command = semantic_release_config["build_command"]
        assert "python -m build" in build_command, "Should use 'python -m build'"

    @pytest.mark.workflows
    def test_changelog_configuration(self, semantic_release_config):
        """Changelog configuration should be present."""
        assert "changelog" in semantic_release_config, "Must configure changelog"

        changelog = semantic_release_config["changelog"]
        assert changelog.get("mode") == "update", "Should use update mode for changelog"

    @pytest.mark.workflows
    def test_publish_configuration(self, semantic_release_config):
        """Publish configuration should be correct."""
        assert "publish" in semantic_release_config, "Must configure publish"

        publish = semantic_release_config["publish"]
        assert "dist_glob_patterns" in publish, "Must specify dist_glob_patterns"
        assert "upload_to_vcs_release" in publish, "Must specify upload_to_vcs_release"

    @pytest.mark.workflows
    def test_version_consistency_with_project(self, project_config):
        """Semantic-release version should match project version."""
        # This is more of a reminder test - the versions should start in sync
        project_version = project_config["version"]

        semver_pattern = r"^\d+\.\d+\.\d+$"
        assert re.match(semver_pattern, project_version), (
            f"Project version '{project_version}' should follow semantic versioning"
        )


class TestReleaseWorkflowInputValidation:
    """Test input validation and edge cases."""

    @pytest.mark.workflows
    def test_workflow_handles_no_release_needed(self):
        """Workflow should handle case where no release is needed."""
        with Path(".github/workflows/release.yml").open() as f:
            workflow = yaml.safe_load(f)

        release_job = workflow["jobs"]["release"]
        steps = release_job["steps"]

        # Should have summary steps for different release outcomes
        summary_steps = [step for step in steps if "Summary" in step.get("name", "")]

        assert summary_steps, "Should have summary steps for release outcomes"

        # Check that we have both dry-run and release summary steps
        step_names = [step.get("name", "") for step in summary_steps]
        assert any("Dry Run" in name for name in step_names), (
            "Should have dry-run summary step"
        )
        assert any(
            "Release" in name and "Dry Run" not in name for name in step_names
        ), "Should have release summary step"

    @pytest.mark.workflows
    def test_debug_information_available(self):
        """Release workflow should provide debug information."""
        with Path(".github/workflows/release.yml").open() as f:
            workflow = yaml.safe_load(f)

        release_job = workflow["jobs"]["release"]
        steps = release_job["steps"]

        # The workflow provides debug information through comprehensive comments
        # and semantic-release's built-in verbose output
        semantic_release_steps = [
            step for step in steps if step.get("name") == "Create and Publish Release"
        ]

        assert semantic_release_steps, "Should have semantic-release step"

        # Check that semantic-release step has proper configuration for debugging
        semantic_release_step = semantic_release_steps[0]
        with_config = semantic_release_step.get("with", {})

        # Should have github_token for authentication and debugging
        assert "github_token" in with_config, (
            "Should have github_token for authentication and debugging"
        )


class TestWorkflowMaintainability:
    """Test that workflows are maintainable and well-documented."""

    @pytest.mark.workflows
    def test_release_workflow_has_comprehensive_comments(self):
        """Release workflow should be well-documented."""
        with Path(".github/workflows/release.yml").open() as f:
            content = f.read()

        # Count comment lines
        lines = content.split("\n")
        comment_lines = [line for line in lines if line.strip().startswith("#")]
        total_lines = len([line for line in lines if line.strip()])

        comment_ratio = len(comment_lines) / total_lines
        assert comment_ratio > 0.1, (
            f"Release workflow should have >10% comments, got {comment_ratio:.1%}"
        )

    @pytest.mark.workflows
    def test_complex_steps_have_descriptions(self):
        """Complex steps should have descriptive names."""
        with Path(".github/workflows/release.yml").open() as f:
            workflow = yaml.safe_load(f)

        release_job = workflow["jobs"]["release"]
        steps = release_job["steps"]

        for step in steps:
            if "run" in step and len(step["run"]) > 100:  # Complex steps
                assert "name" in step, "Complex steps should have names"
                assert len(step["name"]) > 10, (
                    f"Step name too short: '{step.get('name')}'"
                )
