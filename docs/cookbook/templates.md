# Recipe Templates

Use these templates to add new cookbook recipes.

## Templates

- `cookbook/templates/recipe-template.py`
  - General scenario-first recipe scaffold.
- `cookbook/templates/custom-schema-template.py`
  - JSON/schema-first extraction scaffold.

## Author checklist

- Start with concrete problem framing in the module docstring.
- Use shared runtime args from `cookbook.utils.runtime`.
- Include runnable `--mock` and `--no-mock` examples.
- Print concise, success-oriented output (status + key metrics).
- Add or update a page under `docs/cookbook/`.
- Link the page from `mkdocs.yml` cookbook navigation.
