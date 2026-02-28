# v1 Characterization Goldens

These YAML files are the approved (stable) shapes for provider request/config
payloads in the v1 API.

- Run: `just test`
- Update goldens (intentional changes only): `uv run pytest --update-goldens -m "not api"`
