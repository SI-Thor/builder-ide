"""The seat adapters: one module per sibling branch the session drives.

Each adapter holds the *thin* translation between the session's spec-facing
calls and the sibling seat's own code (materialized from its branch by
`siblings.py`). After the seats merge onto `main`, these adapters collapse
into the one HTTP client — that is the design constraint they are written
under: nothing they do may leak into the session script itself.
"""
