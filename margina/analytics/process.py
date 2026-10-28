from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median


@dataclass(frozen=True)
class ProcessEvent:
    event_id: str
    order_id: str
    activity: str
    occurred_at: datetime


def directly_follows(events: Iterable[ProcessEvent]) -> list[dict[str, object]]:
    cases: dict[str, list[ProcessEvent]] = defaultdict(list)
    for event in events:
        cases[event.order_id].append(event)

    transitions: dict[tuple[str, str], list[float]] = defaultdict(list)
    for case_events in cases.values():
        ordered = sorted(case_events, key=lambda event: (event.occurred_at, event.event_id))
        for first, second in pairwise(ordered):
            elapsed_hours = (second.occurred_at - first.occurred_at).total_seconds() / 3600
            if elapsed_hours >= 0:
                transitions[(first.activity, second.activity)].append(elapsed_hours)

    return [
        {
            "from": source,
            "to": target,
            "count": len(durations),
            "median_hours": round(median(durations), 2),
        }
        for (source, target), durations in sorted(transitions.items())
    ]
