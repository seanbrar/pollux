from pollux.config import resolve_config
from pollux.executor import create_executor


def test_default_pipeline_includes_expected_handlers():
    ex = create_executor(
        resolve_config(overrides={"api_key": "k", "model": "gemini-2.0-flash"})
    )
    names = [
        h.__class__.__name__ for h in ex._pipeline
    ]  # accessing internal for contract check
    # Order includes CacheStage in the default pipeline
    assert names[:7] == [
        "SourceHandler",
        "ExecutionPlanner",
        "RemoteMaterializationStage",
        "RateLimitHandler",
        "CacheStage",
        "APIHandler",
        "ResultBuilder",
    ]
