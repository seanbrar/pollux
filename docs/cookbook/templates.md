# Recipe Templates

Use these templates to add cookbook recipes that match the cookbook quality bar.

## Templates

- `cookbook/templates/recipe-template.py`
  - General scenario-first recipe scaffold.
- `cookbook/templates/custom-schema-template.py`
  - JSON/schema-first extraction scaffold.

## Recipe author checklist

- Start with clear problem framing and use/non-use guidance.
- Reuse shared runtime args from `cookbook.utils.runtime`.
- Provide runnable `--mock` and `--no-mock` command examples.
- Print success-oriented output: status, key metrics, and action-ready excerpts.
- Include failure-mode guidance and tuning levers in the docs page.
- Add/update `docs/cookbook/<category>/<recipe>.md` and navigation in `mkdocs.yml`.

## Documentation section contract

Each recipe page should include these sections:

1. `At a glance`
2. `Before you run`
3. `Command`
4. `What to look for`
5. `Tuning levers`
6. `Failure modes`
7. `Extend this recipe`

