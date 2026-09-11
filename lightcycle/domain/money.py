from dataclasses import dataclass


@dataclass(frozen=True)
class Cost:
    micros: int = 0

    @classmethod
    def from_usd(cls, amount) -> "Cost":
        return cls(round((amount or 0.0) * 1_000_000))

    def to_usd(self) -> float:
        return self.micros / 1_000_000

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(self.micros + other.micros)

    def __sub__(self, other: "Cost") -> "Cost":
        return Cost(self.micros - other.micros)

    def __bool__(self) -> bool:
        return self.micros != 0

    def per(self, n):
        return Cost(round(self.micros / n)) if n else None
