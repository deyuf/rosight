"""Tiny fuzzy matcher for table filters.

``matches("odm", "/odom")`` is True: every query character appears in the
text in order (subsequence match, like fzf / lazygit). Plain substrings
always match. Whitespace splits the query into terms that must *all*
match one of the given fields, so ``"scan laser"`` finds
``/scan  sensor_msgs/LaserScan``.
"""

from __future__ import annotations


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def matches(query: str, *fields: str) -> bool:
    terms = query.lower().split()
    if not terms:
        return True
    hays = [f.lower() for f in fields if f]
    return all(any(term in h or _subsequence(term, h) for h in hays) for term in terms)
