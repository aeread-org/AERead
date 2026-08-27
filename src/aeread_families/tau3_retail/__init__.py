"""AERead ``tau3.retail`` family package.

This stage only ships :mod:`cases` (the importer that turns the pinned
upstream tau2-bench retail/base corpus into AERead ``CaseManifest`` records
plus the pilot manifest).  The plugin registration hook, tool bindings,
harness, and measurement scorers are built in later stages and are
deliberately absent here.
"""
