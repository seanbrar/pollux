# Contract-First Testing Patterns

> Scope: Deep Dive. Longer illustrative examples that complement the Concept page.

## Handler contract compliance

```python
# tests/contracts/test_handler_contracts.py
import inspect
import pytest

from pollux.pipeline.source_handler import SourceHandler

def test_handler_signature_is_contractual():
    sig = inspect.signature(SourceHandler.handle)
    params = list(sig.parameters.values())
    assert params[0].name == "self"
    assert len(params) == 2, "handle(self, command)"
    assert "return" in sig.annotations, "Result[...] return type annotated"

@pytest.mark.anyio
async def test_handler_is_pure_and_deterministic(initial_command):
    h = SourceHandler()
    r1 = await h.handle(initial_command)
    r2 = await h.handle(initial_command)
    assert type(r1) is type(r2)
    assert r1 == r2
```

## Command state immutability

```python
# tests/contracts/test_command_states.py
import pytest
from copy import deepcopy
from pollux.core.types import InitialCommand

def test_commands_are_immutable(initial_command):
    with pytest.raises(AttributeError):
        initial_command.prompts = ("nope",)

def test_copy_equals_original(initial_command):
    cp = deepcopy(initial_command)
    assert cp == initial_command
```

## Planner purity

```python
# tests/contracts/test_planner_purity.py
import inspect
from pollux.pipeline.planner import ExecutionPlanner

FORBIDDEN_IMPORTS = {"google", "genai", "vertexai"}

def test_planner_has_no_sdk_imports():
    src = inspect.getsource(ExecutionPlanner)
    assert not any(x in src for x in FORBIDDEN_IMPORTS)
```

## Error semantics

```python
# tests/contracts/test_error_semantics.py
import pytest
from pollux.pipeline.source_handler import SourceHandler
from pollux.core.types import InitialCommand, Failure, Success

@pytest.mark.anyio
async def test_handlers_return_result_not_throw(bad_initial_command):
    res = await SourceHandler().handle(bad_initial_command)
    assert isinstance(res, (Success, Failure))
```

## Architectural fitness (meta)

```python
# tests/contracts/test_architectural_fitness.py
import glob, re

def test_tests_remain_simple():
    for path in glob.glob("tests/**/*.py", recursive=True):
        text = open(path, "r", encoding="utf-8").read()
        assert text.count("mock") < 25
        assert len(text.splitlines()) < 600

def test_no_forbidden_patterns():
    bad = re.compile(r"from\s+google\..*import|vertexai|genai")
    text = open("src/pollux/pipeline/planner.py", "r", encoding="utf-8").read()
    assert not bad.search(text)
```
