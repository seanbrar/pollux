"""Data-centric conversation extension for Gemini batch processing.

This module provides a minimal, data-driven conversation extension that implements
the A+B hybrid design with single pipeline seam. The extension focuses on multi-turn
conversations with advanced batch processing while delegating complexity to the core.

Key components:
- Conversation: Tiny facade for conversation operations
- ConversationPolicy: Immutable policy controlling behavior
- PromptSet: Prompts with execution mode (single/sequential/vectorized)
- ConversationPlan: Compiled execution plan for auditability
- compile_conversation: Pure function for plan compilation
- execute_plan: Single pipeline seam for execution

Architecture principles:
- Data-centric design with immutable state
- Pure compile-then-execute pattern
- Single pipeline seam via GeminiExecutor
- Minimal facade with essential operations
- Full alignment with architecture rubric

Example:
    from pollux import create_executor
    from pollux.extensions import Conversation, PromptSet

    executor = create_executor()
    conv = Conversation.start(executor)

    # Simple usage
    conv = await conv.ask("Hello")

    # Advanced batch with policy
    from pollux.extensions import ConversationPolicy
    policy = ConversationPolicy.cost_saver()
    conv, answers, metrics = await conv.with_policy(policy).run(
        PromptSet.vectorized("Q1", "Q2", "Q3")
    )
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol

from pollux.core.exceptions import InvariantViolationError
from pollux.core.types import (
    InitialCommand,
    ResultEnvelope,
    explain_invalid_result_envelope,
    is_result_envelope,
)

from .conversation_planner import compile_conversation
from .conversation_types import (
    BatchMetrics,
    ConversationAnalytics,
    ConversationPolicy,
    ConversationState,
    PromptSet,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable

    class ExecutorLike(Protocol):
        """Minimal executor protocol used by the extension.

        Keeps extensions decoupled and limits type-checker traversal
        while preserving a typed seam at the executor boundary.
        """

        config: Any

        def execute(self, _command: InitialCommand) -> Awaitable[ResultEnvelope]:
            """Execute a command and return a result envelope."""

    from .conversation_planner import ConversationPlan


class Conversation:
    """Immutable conversation facade over the batch pipeline.

    Wraps a `ConversationState` and delegates execution to the single
    `GeminiExecutor.execute` seam. Every operation returns a new instance.
    """

    def __init__(self, state: ConversationState, executor: ExecutorLike):
        """Initialize a conversation with state and executor."""
        self._state = state
        self._executor = executor

    @classmethod
    def start(
        cls, executor: ExecutorLike, *, sources: Iterable[Any] = ()
    ) -> Conversation:
        """Create a new conversation with optional initial sources."""
        return cls(ConversationState(sources=tuple(sources), turns=()), executor)

    @property
    def state(self) -> ConversationState:
        """Return the current immutable conversation state."""
        return self._state

    def with_policy(self, policy: ConversationPolicy) -> Conversation:
        """Return a new conversation with the provided policy applied."""
        return Conversation(
            replace(self._state, policy=policy, version=self._state.version + 1),
            self._executor,
        )

    def with_sources(self, sources: Iterable[Any]) -> Conversation:
        """Return a new conversation with replaced sources.

        Accepts a single path-like string or an iterable of sources.
        """
        # Coerce single string-like into a single-element tuple to avoid
        # accidental character-splitting when a path is passed as a string.
        new_sources = (sources,) if isinstance(sources, str | bytes) else tuple(sources)
        return Conversation(
            replace(self._state, sources=new_sources, version=self._state.version + 1),
            self._executor,
        )

    async def ask(self, prompt: str) -> Conversation:
        """Ask a single prompt and append the result as a new turn."""
        ps = PromptSet.single(prompt)
        conv, answers, _ = await self.run(ps)
        return conv  # answers available at conv.state.last.assistant

    async def run(
        self, prompt_set: PromptSet
    ) -> tuple[Conversation, tuple[str, ...], BatchMetrics]:
        """Execute a `PromptSet` and return the updated conversation and metrics.

        Args:
            prompt_set: Prompts plus execution mode (single/sequential/vectorized).

        Returns:
            A tuple of (new_conversation, answers, batch_metrics).
        """
        policy = self._state.policy
        plan = compile_conversation(self._state, prompt_set, policy)

        # Single pipeline seam: build InitialCommand and execute
        cfg = self._executor.config
        frozen = cfg.to_frozen() if hasattr(cfg, "to_frozen") else cfg
        cmd = InitialCommand(
            sources=plan.sources,
            prompts=plan.prompts,
            config=frozen,
            history=plan.history,
            options=plan.options,
        )
        res: ResultEnvelope = await self._executor.execute(
            cmd
        )  # core builds answers+metrics; do not reimplement

        # Immediate validation: fail fast on invalid envelopes
        if not is_result_envelope(res):
            reason = explain_invalid_result_envelope(res) or "Invalid ResultEnvelope"
            raise InvariantViolationError(reason, stage_name="conversation")

        # Map results minimally → Exchanges (no parsing/validation logic here)
        status_str = str(res.get("status")).lower()
        is_error = status_str == "error"
        answers = tuple(str(a) for a in (res.get("answers") or []))
        usage = res.get("usage") or {}
        metrics = res.get("metrics") or {}
        token_val = metrics.get("token_validation") or {}

        # Extract validation warnings and surface them
        validation_warnings = res.get("validation_warnings") or ()
        if isinstance(validation_warnings, str):
            validation_warnings = (validation_warnings,)
        elif not isinstance(validation_warnings, list | tuple):
            validation_warnings = ()
        else:
            validation_warnings = tuple(str(w) for w in validation_warnings)

        # Add token estimation accuracy warnings for large mismatches
        warnings_list = list(validation_warnings)
        actual_tokens = token_val.get("actual")
        estimated_max = token_val.get("estimated_max")
        in_range = token_val.get("in_range")

        if actual_tokens and estimated_max and in_range is False:
            ratio = actual_tokens / estimated_max
            if ratio > 2.0:  # More than 2x over estimate
                warnings_list.append(
                    f"Token usage {actual_tokens} significantly exceeded estimate {estimated_max} ({ratio:.1f}x)"
                )

        validation_warnings = tuple(warnings_list)

        # Pure delegation to mode for exchange formatting
        execution_metadata = {
            "error": is_error,
            "estimate_min": token_val.get("estimated_min"),
            "estimate_max": token_val.get("estimated_max"),
            "actual_tokens": token_val.get("actual")
            or usage.get("total_tokens")
            or usage.get("total_token_count"),
            "in_range": token_val.get("in_range"),
            "warnings": validation_warnings,
        }

        new_exchanges = prompt_set.mode.format_exchanges(
            prompt_set.prompts, answers, execution_metadata
        )

        new_state = replace(
            self._state,
            turns=(*self._state.turns, *new_exchanges),
            version=self._state.version + 1,
        )

        # Improved per-prompt metrics handling
        # Try to extract per-prompt metrics from the metrics dict if available
        per_prompt_metrics = []
        if "per_prompt" in metrics and isinstance(metrics["per_prompt"], list | tuple):
            # Use actual per-prompt metrics if available
            per_prompt_metrics = list(metrics["per_prompt"])
        else:
            # Fall back to distributing totals across prompts
            base_metrics = dict(usage.items()) if isinstance(usage, dict) else {}
            if not base_metrics and isinstance(metrics, dict):
                # Try to use metrics dict as base if usage is empty
                base_metrics = {
                    k: v
                    for k, v in metrics.items()
                    if isinstance(v, int | float) and k != "token_validation"
                }
            per_prompt_metrics = [dict(base_metrics) for _ in answers]

        # Ensure we have the right number of per-prompt entries
        while len(per_prompt_metrics) < len(answers):
            per_prompt_metrics.append({})
        per_prompt = tuple(per_prompt_metrics[: len(answers)])

        # Build totals from usage or metrics
        totals = dict(usage.items()) if isinstance(usage, dict) else {}
        if not totals and isinstance(metrics, dict):
            totals = {
                k: v
                for k, v in metrics.items()
                if isinstance(v, int | float) and k != "token_validation"
            }

        return (
            Conversation(new_state, self._executor),
            answers,
            BatchMetrics(per_prompt=per_prompt, totals=totals),
        )

    def plan(
        self, prompt_set: PromptSet, policy: ConversationPolicy | None = None
    ) -> ConversationPlan:
        """Return the compiled plan for inspection without executing.

        Useful for debugging, audits, and explainability UIs.
        """
        return compile_conversation(
            self._state, prompt_set, policy or self._state.policy
        )

    # tiny analytics helper (pure; or move to conversation_analytics.py)
    def analytics(self) -> ConversationAnalytics:
        """Summarize conversation analytics from recorded exchanges."""
        turns = self._state.turns
        n = len(turns)
        errs = sum(t.error for t in turns)
        tot_est = (
            sum(t.estimate_max for t in turns if t.estimate_max is not None) or None
        )
        tot_act = (
            sum(t.actual_tokens for t in turns if t.actual_tokens is not None) or None
        )
        acc = (tot_act / tot_est) if (tot_act and tot_est and tot_est > 0) else None
        total_user = sum(len(t.user) for t in turns)
        total_assist = sum(len(t.assistant) for t in turns)
        avg_len = (total_assist / n) if n else 0.0
        return ConversationAnalytics(
            n,
            errs,
            (n - errs) / n if n else 1.0,
            tot_est,
            tot_act,
            acc,
            avg_len,
            total_user,
            total_assist,
        )
