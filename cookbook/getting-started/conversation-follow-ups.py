#!/usr/bin/env python3
"""🎯 Recipe: Conversation Follow-ups With Persistence

When you need to: Start a conversation, ask a question, then ask a coherent
follow-up while persisting state via `ConversationEngine` + `JSONStore`.

Ingredients:
- `GEMINI_API_KEY` set in the environment
- Optional: a file or directory of sources to ground the conversation

What you'll learn:
- Initialize store-backed `ConversationEngine` and persist by id
 - Ask an initial question and a follow-up that leverages context
- Inspect appended exchanges and basic metrics

Difficulty: ⭐⭐
Time: ~8-10 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pollux import create_executor
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore


async def main_async(
    conversation_id: str, _sources: list[Path] | None, store_path: Path
) -> None:
    ex = create_executor()
    store = JSONStore(str(store_path))
    engine = ConversationEngine(ex, store)

    # Optional grounding: attach sources on the first turn by embedding context
    # in the first prompt, or rely on your system instruction. For simplicity,
    # we ask generic questions here.

    first = await engine.ask(conversation_id, "What are the central themes?")
    print("\nQ1 → A1 (first 200 chars):\n", first.assistant[:200], sep="")

    # Follow-up referring back to the previous answer
    second = await engine.ask(
        conversation_id, "Based on that, list 3 actionable next steps."
    )
    print("\nQ2 → A2 (first 200 chars):\n", second.assistant[:200], sep="")

    # Inspect persisted state
    state = await store.load(conversation_id)
    print(f"\n💾 Stored turns: {len(state.turns)} | version: {state.version}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Conversation follow-ups demo")
    parser.add_argument("conversation_id", help="Persistent conversation id")
    parser.add_argument(
        "--store",
        type=Path,
        default=Path("outputs/conversations.json"),
        help="Path for JSON store",
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Optional files to ground context (not required in this demo)",
    )
    args = parser.parse_args()
    srcs = [Path(p) for p in (args.sources or [])]
    asyncio.run(main_async(args.conversation_id, srcs or None, args.store))


if __name__ == "__main__":
    main()
