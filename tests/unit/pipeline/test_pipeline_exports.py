def test_pipeline_exports_classes():
    from pollux.pipeline import (
        APIHandler,
        BaseAsyncHandler,
        ExecutionPlanner,
        ResultBuilder,
        SourceHandler,
    )

    # Simple sanity checks that exports are classes/callables
    assert callable(APIHandler)
    assert callable(ExecutionPlanner)
    assert callable(ResultBuilder)
    assert callable(SourceHandler)

    # Protocol is type-only but should still be importable
    assert BaseAsyncHandler is not None
