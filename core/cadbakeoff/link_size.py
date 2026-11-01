#!/usr/bin/env python3
"""Attribute a Rust binary's linked code to the crates it came from.

``nm --print-size --size-sort`` gives every symbol's size. Each Rust symbol
carries its crate in the path, so grouping by the first path component that
is a known crate attributes the binary's weight to the crates that were
actually linked in.

    python3 link_size.py <binary> <crate names...>
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict


def main() -> int:
    binary = sys.argv[1]
    crates = set(sys.argv[2:])
    out = subprocess.run(
        ["nm", "--print-size", "--size-sort", "--radix=d", binary],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    sizes: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for line in out.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) < 4:
            continue
        try:
            size = int(parts[1])
        except ValueError:
            continue
        name = parts[3]
        total += size
        owner = None
        for component in mangled_path(name):
            if component in crates:
                owner = component
                break
        if owner is None:
            owner = "<std/alloc/other>"
        sizes[owner] += size
        counts[owner] += 1
    print(f"binary: {binary}")
    print(f"total symbol bytes: {total:,}")
    print(f"{'crate':<34}{'bytes':>14}{'share':>8}{'symbols':>10}")
    for crate, size in sorted(sizes.items(), key=lambda kv: -kv[1]):
        print(
            f"{crate:<34}{size:>14,}{100.0 * size / total:>7.2f}%{counts[crate]:>10,}"
        )
    return 0


def mangled_path(name: str) -> list[str]:
    """The path components of a Rust symbol's mangled name.

    Rust v0 mangling writes each path element as its length then its name,
    so ``_RNvCs9iSNRVgddEv_17solidcraft_engine6frames`` holds the crate
    ``solidcraft_engine`` and the module ``frames``. The length prefix is
    what tells the two apart, so it is honoured exactly: a component is
    taken only when the number of characters that follow matches the prefix.
    """
    components: list[str] = []
    index = 0
    length = len(name)
    while index < length:
        char = name[index]
        if not char.isdigit():
            index += 1
            continue
        end = index
        while end < length and name[end].isdigit():
            end += 1
        try:
            count = int(name[index:end])
        except ValueError:
            index = end
            continue
        start = end
        stop = start + count
        if 0 < count and stop <= length:
            text = name[start:stop]
            if all(c.isalnum() or c == "_" for c in text) and not text[0].isdigit():
                components.append(text)
        index = end
    return components


if __name__ == "__main__":
    sys.exit(main())
