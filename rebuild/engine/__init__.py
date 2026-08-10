"""Coverage engine for the Blacksburg prayer-walk PWA.

Public surface is contracts.md §2 and nothing else:

    from rebuild.engine import propose
    proposals = propose(trace, network)

`Network` is exported so a caller can pay the projection/index cost once and
hand the same object to every call.
"""

from .coverage import Network, Segment, propose

__all__ = ["propose", "Network", "Segment"]
