"""MkDocs hook: align Material's responsive breakpoints with the Pollux theme.

Material defines three layout modes (mobile / tablet / desktop) with
breakpoints at ~60 em and ~76.25 em.  Pollux uses a single threshold at
51.2 em.  This hook rewrites Material's breakpoint values in-memory so
its media queries match, eliminating visual jumps in the tablet zone.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files

log = logging.getLogger("mkdocs.hooks.patch_material_css")

# Material breakpoint → Pollux replacement (media-query context only).
_REPLACEMENTS = {
    "max-width:76.234375em": "max-width:51.199em",
    "max-width:59.984375em": "max-width:51.199em",
    "min-width:76.25em": "min-width:51.2em",
    "min-width:60em": "min-width:51.2em",
}

# Only patch files whose dest_uri matches these prefixes.
_CSS_PREFIXES = ("assets/stylesheets/main.", "assets/stylesheets/palette.")


def on_files(files: Files, *, config: MkDocsConfig) -> Files:  # noqa: ARG001
    """Rewrite Material CSS breakpoints to match the Pollux single-threshold layout."""
    for f in files:
        if not any(f.dest_uri.startswith(p) for p in _CSS_PREFIXES):
            continue
        if not f.dest_uri.endswith(".css"):
            continue

        css = f.content_string
        patched = css
        for old, new in _REPLACEMENTS.items():
            patched = patched.replace(old, new)

        if patched != css:
            f.content_string = patched
            log.info("Patched breakpoints in %s", f.dest_uri)

    return files
