"""
Test helper utilities and data models.

This module contains reusable utility classes and data models that can be
imported explicitly by test modules.
"""

from dataclasses import dataclass
from pathlib import Path
import subprocess

from pydantic import BaseModel, Field


# --- Data Models ---
class MockCommit(BaseModel):
    """A Pydantic model to represent a commit for testing."""

    type: str = "feat"  # Default type
    scope: str
    descriptions: list[str]
    short_hash: str
    hexsha: str
    breaking_descriptions: list[str] = Field(default_factory=list)
    linked_issues: list[str] = Field(default_factory=list)

    def __lt__(self, other: "MockCommit") -> bool:
        """Provides a default sort order for stable sorting in Jinja."""
        if not isinstance(other, MockCommit):
            return NotImplemented
        return self.short_hash < other.short_hash


# --- Workflow Testing Utilities ---
@dataclass
class ActResult:
    """Wrapper for act command results with convenient assertion methods."""

    stdout: str
    stderr: str
    returncode: int

    def assert_success(self, context: str = "Act command") -> "ActResult":
        """Assert that the command succeeded."""
        assert self.returncode == 0, (
            f"{context} failed with exit code {self.returncode}. Stderr: {self.stderr}"
        )
        return self

    def assert_contains(self, text: str, context: str = "Output") -> "ActResult":
        """Assert that stdout contains the expected text."""
        assert text in self.stdout, (
            f"{context} should contain '{text}'. "
            f"Actual stdout: {self.stdout[:500]}... "
            f"Stderr: {self.stderr}"
        )
        return self

    def assert_job_succeeded(self) -> "ActResult":
        """Assert that the act job completed successfully."""
        return self.assert_contains("Job succeeded", "Act job execution")


@dataclass
class ActCommand:
    """Builder for act commands with common patterns."""

    executable: str
    event: str = "workflow_dispatch"
    job: str | None = None
    workflow_file: str | None = None
    dry_run: bool = False
    verbose: bool = False
    inputs: dict[str, str] | None = None
    secrets: dict[str, str] | None = None
    container_architecture: str | None = None

    def __post_init__(self):
        if self.inputs is None:
            self.inputs = {}
        if self.secrets is None:
            self.secrets = {}

    def with_job(self, job: str) -> "ActCommand":
        """Target a specific job."""
        self.job = job
        return self

    def with_workflow(self, workflow_file: str) -> "ActCommand":
        """Specify workflow file."""
        self.workflow_file = workflow_file
        return self

    def with_dry_run(self, *, dry_run: bool = True) -> "ActCommand":
        """Enable/disable dry run mode."""
        self.dry_run = dry_run
        return self

    def with_verbose(self, *, verbose: bool = True) -> "ActCommand":
        """Enable/disable verbose output."""
        self.verbose = verbose
        return self

    def with_input(self, key: str, value: str) -> "ActCommand":
        """Add workflow input."""
        if self.inputs is None:
            self.inputs = {}
        self.inputs[key] = value
        return self

    def with_secret(self, key: str, value: str) -> "ActCommand":
        """Add secret."""
        if self.secrets is None:
            self.secrets = {}
        self.secrets[key] = value
        return self

    def with_container_architecture(self, architecture: str) -> "ActCommand":
        """Set container architecture."""
        self.container_architecture = architecture
        return self

    def build_args(self) -> list[str]:
        """Build the command arguments list."""
        args = [self.executable, self.event]

        if self.job:
            args.extend(["-j", self.job])

        if self.workflow_file:
            args.extend(["-W", self.workflow_file])

        if self.dry_run:
            args.append("--dryrun")

        if self.verbose:
            args.append("-v")

        if self.container_architecture:
            args.extend(["--container-architecture", self.container_architecture])

        if self.inputs:
            for key, value in self.inputs.items():
                args.extend(["--input", f"{key}={value}"])

        if self.secrets:
            for key, value in self.secrets.items():
                args.extend(["--secret", f"{key}={value}"])

        return args

    def run(self, cwd: Path | None = None) -> ActResult:
        """Execute the act command."""
        result = subprocess.run(
            self.build_args(),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return ActResult(
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode
        )


class GitHelper:
    """Helper for git operations with consistent error handling."""

    def __init__(self, git_executable: str, repo_path: Path):
        self.git_executable = git_executable
        self.repo_path = repo_path

    def run(
        self, args: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repository."""
        cmd = [self.git_executable, *args]
        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return result

    def add_and_commit(self, files: list[str], message: str) -> "GitHelper":
        """Add files and create a commit."""
        self.run(["add", *files])
        self.run(["commit", "-m", message])
        return self

    def create_feature_commit(
        self, feature_name: str = "amazing new feature"
    ) -> "GitHelper":
        """Create a standard feature commit for testing."""
        feature_file = self.repo_path / f"{feature_name.replace(' ', '_')}.txt"
        feature_file.write_text(f"A {feature_name}")
        return self.add_and_commit([feature_file.name], f"feat: add {feature_name}")

    def tag_exists(self, tag: str) -> bool:
        """Check if a git tag exists."""
        result = self.run(["rev-parse", tag], check=False)
        return result.returncode == 0

    def assert_tag_exists(self, tag: str) -> "GitHelper":
        """Assert that a tag exists."""
        assert self.tag_exists(tag), f"Expected git tag '{tag}' to exist but it doesn't"
        return self

    def assert_tag_not_exists(self, tag: str) -> "GitHelper":
        """Assert that a tag does not exist."""
        assert not self.tag_exists(tag), (
            f"Expected git tag '{tag}' to not exist but it does"
        )
        return self


class ActTestHelper:
    """High-level helper for common act testing scenarios."""

    def __init__(self, act_executable: str, git_helper: GitHelper):
        self.act_executable = act_executable
        self.git = git_helper

    def create_act_command(self) -> ActCommand:
        """Create a new ActCommand instance."""
        return ActCommand(self.act_executable)

    def run_lint_workflow(self) -> ActResult:
        """Run the lint-workflows job."""
        return (
            self.create_act_command()
            .with_job("lint-workflows")
            .with_container_architecture("linux/amd64")  # Fix for Apple M-series chips
            .run(self.git.repo_path)
        )

    def run_pre_release_checks_dry_run(self) -> ActResult:
        """Run pre-release-checks in dry run mode."""
        return (
            self.create_act_command()
            .with_job("pre-release-checks")
            .with_dry_run(dry_run=True)
            .with_verbose(verbose=True)
            .with_container_architecture("linux/amd64")  # Fix for Apple M-series chips
            .run(self.git.repo_path)
        )

    def run_release_workflow_dry_run(self) -> ActResult:
        """Run release workflow in dry run mode for testing."""
        return (
            self.create_act_command()
            .with_job("release")
            .with_workflow(".github/workflows/release.yml")
            .with_input("dry_run", "true")
            .with_dry_run(dry_run=True)
            .with_verbose(verbose=True)
            .with_container_architecture("linux/amd64")  # Fix for Apple M-series chips
            .run(self.git.repo_path)
        )

    def run_release_workflow(
        self, *, github_token: str, dry_run: bool = False, with_gh_token: bool = False
    ) -> ActResult:
        """Run the release workflow with explicit token."""
        cmd = (
            self.create_act_command()
            .with_job("release")
            .with_workflow(".github/workflows/release.yml")
            .with_container_architecture("linux/amd64")  # Fix for Apple M-series chips
        )

        if dry_run:
            cmd.with_input("dry_run", "true")
        else:
            cmd.with_input("dry_run", "false")

        # Use the provided github_token instead of environment lookup
        cmd.with_secret("GITHUB_TOKEN", github_token)

        # Conditionally add GH_TOKEN for semantic-release
        if with_gh_token:
            cmd.with_secret("GH_TOKEN", "dummy-gh-token-for-release")

        return cmd.run(self.git.repo_path)
