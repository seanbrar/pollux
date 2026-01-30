# Pipeline Internals

Core pipeline handlers and supporting utilities. These are stable but considered lower-level than the public helpers.

## Handler Protocol

::: pollux.pipeline.base.BaseAsyncHandler

## Handlers

::: pollux.pipeline.source_handler.SourceHandler

::: pollux.pipeline.planner.ExecutionPlanner

::: pollux.pipeline.remote_materialization.RemoteMaterializationStage

::: pollux.pipeline.cache_stage.CacheStage

::: pollux.pipeline.api_handler.APIHandler

::: pollux.pipeline.rate_limit_handler.RateLimitHandler

::: pollux.pipeline.result_builder.ResultBuilder

## Execution State and Identity

::: pollux.pipeline.execution_state.ExecutionHints

::: pollux.pipeline.cache_identity.det_shared_key

## Type Erasure (Internal)

::: pollux.pipeline._erasure.ErasedAsyncHandler
