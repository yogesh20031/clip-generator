"""A tiny progress abstraction so the pipeline doesn't care whether it reports to MCP or a CLI bar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

ProgressFn = Callable[[float, str], None]


@dataclass
class StageProgress:
    """Maps per-stage fractions onto one monotonic 0-1 progress value.

    `stages` is an ordered mapping of stage name -> relative weight.
    """

    stages: dict[str, float]
    callback: ProgressFn | None = None
    _total: float = field(init=False)
    _done_before: dict[str, float] = field(init=False, default_factory=dict)
    _last: float = field(init=False, default=-1.0)

    def __post_init__(self) -> None:
        self._total = sum(self.stages.values()) or 1.0
        acc = 0.0
        for name, weight in self.stages.items():
            self._done_before[name] = acc
            acc += weight

    def report(self, stage: str, fraction: float, message: str = "") -> None:
        fraction = max(0.0, min(1.0, fraction))
        weight = self.stages.get(stage, 0.0)
        value = (self._done_before.get(stage, 0.0) + weight * fraction) / self._total
        # The MCP spec requires progress to increase monotonically.
        if value <= self._last:
            value = min(1.0, self._last + 1e-4)
        self._last = value
        if self.callback is not None:
            self.callback(value, message or stage)

    def sub(self, stage: str) -> ProgressFn:
        """A (fraction, message) callback scoped to one stage."""
        return lambda frac, msg: self.report(stage, frac, msg)
