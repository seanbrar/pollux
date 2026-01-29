import pytest

from pollux.extensions.token_counting import (
    ErrorInfo,
    GeminiTokenCounter,
    InvalidContentError,
    TokenCountError,
    TokenCountFailure,
    TokenCountResult,
    TokenCountSuccess,
    ValidContent,
    _estimate_tokens_fallback,
    count_gemini_tokens,
)

pytestmark = [pytest.mark.unit, pytest.mark.smoke]


def test_valid_content_from_text_success() -> None:
    content = ValidContent.from_text("hello world")
    assert content.text == "hello world"
    assert content.content_type == "text"
    assert content.char_count == len("hello world")


@pytest.mark.parametrize("bad", ["", "   \n\t   "])
def test_valid_content_from_text_rejects_empty(bad: str) -> None:
    with pytest.raises(InvalidContentError):
        ValidContent.from_text(bad)


def test_valid_content_from_text_rejects_too_large() -> None:
    huge = "x" * (10_000_000 + 1)
    with pytest.raises(InvalidContentError):
        ValidContent.from_text(huge)


def test_error_info_preserves_recovery_hint() -> None:
    err = TokenCountError("boom", recovery_hint="do X")
    info = ErrorInfo.from_exception(err)
    assert info.message == "boom"
    assert info.error_type.endswith("TokenCountError")
    assert info.recovery_hint == "do X"


def test_estimate_tokens_fallback_basic() -> None:
    assert _estimate_tokens_fallback("") == 0
    assert _estimate_tokens_fallback("   ") == 0
    # Minimal non-empty returns at least 1
    assert _estimate_tokens_fallback("a") == 1
    assert _estimate_tokens_fallback("abcd") == 1
    assert _estimate_tokens_fallback("abcdefgh") >= 2


@pytest.mark.asyncio
async def test_counter_with_fallback_and_hints() -> None:
    content = ValidContent.from_text("abcdefgh")  # 8 chars
    # Base fallback: 8 // 4 = 2

    class Hint:
        widen_max_factor = 2.5
        clamp_max_tokens = 4

    counter = GeminiTokenCounter(use_fallback_estimation=True)
    res: TokenCountResult = await counter.count_tokens(content, hints=(Hint(),))
    assert isinstance(res, TokenCountSuccess)
    # Widen to 5 then clamp to 4
    assert res.count == 4
    assert res.metadata["counting_method"] == "fallback_estimation"
    assert res.metadata["base_count"] == 2
    assert res.metadata["hints_applied"] is True


@pytest.mark.asyncio
async def test_counter_handles_token_count_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = ValidContent.from_text("hello")

    # Patch the internal API function to raise a domain error
    from pollux.extensions import token_counting as mod

    def boom(text: str, model_name: str) -> int:  # noqa: ARG001
        raise TokenCountError("service down", recovery_hint="try later")

    monkeypatch.setattr(mod, "_count_tokens_with_gemini_api", boom)

    counter = GeminiTokenCounter()
    res = await counter.count_tokens(content)
    assert isinstance(res, TokenCountFailure)
    assert res.error.message == "service down"
    assert res.error.recovery_hint == "try later"
    assert res.metadata["content_type"] == "text"
    assert res.metadata["attempted_char_count"] == content.char_count


@pytest.mark.asyncio
async def test_counter_handles_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = ValidContent.from_text("hello")

    from pollux.extensions import token_counting as mod

    def boom(text: str, model_name: str) -> int:  # noqa: ARG001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mod, "_count_tokens_with_gemini_api", boom)

    counter = GeminiTokenCounter()
    res = await counter.count_tokens(content)
    assert isinstance(res, TokenCountFailure)
    assert res.error.message == "kaboom"
    assert res.metadata["content_type"] == "text"
    # Ensure attempted_char_count is consistently present
    assert res.metadata["attempted_char_count"] == content.char_count


@pytest.mark.asyncio
async def test_convenience_function_wraps_invalid_content() -> None:
    res = await count_gemini_tokens(123)  # type: ignore[arg-type]
    assert isinstance(res, TokenCountFailure)
    assert res.error.error_type.endswith("InvalidContentError")
    assert res.metadata["attempted_text_length"] == 0


@pytest.mark.asyncio
async def test_counter_success_with_patched_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = ValidContent.from_text("hello world")

    from pollux.extensions import token_counting as mod

    def ok(text: str, model_name: str) -> int:  # noqa: ARG001
        return 10

    monkeypatch.setattr(mod, "_count_tokens_with_gemini_api", ok)

    counter = GeminiTokenCounter()
    res = await counter.count_tokens(content, model_name="gemini-x")
    assert isinstance(res, TokenCountSuccess)
    assert res.count == 10
    assert res.metadata["model_name"] == "gemini-x"
    assert res.metadata["counting_method"] == "gemini_api"


@pytest.mark.asyncio
async def test_counter_invokes_api_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    content = ValidContent.from_text("hello")

    from pollux.extensions import token_counting as mod

    called_thread: int | None = None

    def record_thread(text: str, model_name: str) -> int:  # noqa: ARG001
        nonlocal called_thread
        called_thread = threading.get_ident()
        return 7

    monkeypatch.setattr(mod, "_count_tokens_with_gemini_api", record_thread)

    counter = GeminiTokenCounter()
    main_tid = threading.get_ident()
    res = await counter.count_tokens(content)

    assert isinstance(res, TokenCountSuccess)
    assert res.count == 7
    # Ensure the call was made on a different thread than the test's thread
    assert called_thread is not None
    assert called_thread != main_tid


@pytest.mark.asyncio
async def test_counter_with_reused_client() -> None:
    # Fake minimal client shape
    class _Result:
        def __init__(self, total: int) -> None:
            self.total_tokens = total

    class _Models:
        def count_tokens(self, *, model: str, contents: str) -> _Result:  # noqa: ARG002
            return _Result(42)

    class _Client:
        def __init__(self) -> None:
            self.models = _Models()

    content = ValidContent.from_text("hello client")
    counter = GeminiTokenCounter(client=_Client())
    out = await counter.count_tokens(content)
    assert isinstance(out, TokenCountSuccess)
    assert out.count == 42
    assert out.metadata["counting_method"] == "gemini_api"


@pytest.mark.asyncio
async def test_hint_validation_and_behavior() -> None:
    content = ValidContent.from_text("abcdefgh")  # 8 chars, fallback = 2

    class HintBad:
        widen_max_factor = 0.5  # ignored (<= 1)
        clamp_max_tokens = 0  # ignored (< 1)

    class HintGood:
        widen_max_factor = 1.5  # widens 2 -> 3
        clamp_max_tokens = 2  # clamps back to 2

    counter = GeminiTokenCounter(use_fallback_estimation=True)
    res = await counter.count_tokens(content, hints=(HintBad(), HintGood()))
    assert isinstance(res, TokenCountSuccess)
    assert res.count == 2
