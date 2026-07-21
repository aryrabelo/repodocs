#!/usr/bin/env python3
"""CI guardrail: no distributed module may grow into an unmaintainable monolith.

Fails if any shipped source file under src/repodocs/ exceeds MAX_LINES. Test code
lives under tests/ and is exempt (it is not distributed and may be long).
"""
import sys
from pathlib import Path

MAX_LINES = 500
PKG = Path(__file__).resolve().parent.parent / "src" / "repodocs"


def offenders() -> list[tuple[str, int]]:
    bad = []
    for p in sorted(PKG.rglob("*.py")):
        n = sum(1 for _ in p.open("rb"))
        if n > MAX_LINES:
            bad.append((str(p.relative_to(PKG.parent.parent)), n))
    return bad


def main() -> int:
    bad = offenders()
    for path, n in bad:
        print(f"{path}: {n} lines exceeds the {MAX_LINES}-line module limit", file=sys.stderr)
    if bad:
        print("split the module before it becomes another monolith", file=sys.stderr)
        return 1
    print(f"module size: ok (all src/repodocs modules within {MAX_LINES} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
