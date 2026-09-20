"""Offline balance simulator for Shardfall waves."""

from dataclasses import dataclass

# Fraction of a tower's theoretical damage that lands on target in practice (misses, overkill).
HIT_EFFICIENCY = 0.7


@dataclass
class TowerSpec:
    name: str
    cost: int
    damage: float
    fire_rate: float

    def dps(self) -> float:
        return self.damage * self.fire_rate * HIT_EFFICIENCY


def dps_per_gold(tower: TowerSpec) -> float:
    """Damage per second bought by each gold spent; used to compare towers of different price."""
    return tower.dps() / tower.cost


def effective_damage(raw: float, armor: float) -> float:
    """A single hit after armor. Mirrors Enemy.take_damage: at least 1 damage always lands."""
    return max(1.0, raw - armor)


def time_on_path(path_length_px: float, enemy_speed: float, chill_slow: float = 0.0) -> float:
    """Seconds an enemy spends walking the path, optionally slowed by Chill."""
    return path_length_px / (enemy_speed * (1.0 - chill_slow))


def simulate_wave(
    towers: list[TowerSpec],
    enemy_hp: float,
    enemy_armor: float,
    path_length_px: float,
    speed: float,
) -> bool:
    """Return True if the towers can kill one enemy before it reaches the Shard Core."""
    total_dps = sum(
        effective_damage(t.damage, enemy_armor) * t.fire_rate * HIT_EFFICIENCY for t in towers
    )
    return total_dps * time_on_path(path_length_px, speed) >= enemy_hp


class BalanceReport:
    def __init__(self, towers: list[TowerSpec]) -> None:
        self.towers = towers

    def summarize(self) -> str:
        lines = [f"{t.name}: {dps_per_gold(t):.3f} dps per gold" for t in self.towers]
        return "\n".join(lines)


if __name__ == "__main__":
    specs = [
        TowerSpec("Arrow", 50, 12, 1.5),
        TowerSpec("Cannon", 120, 40, 0.4),
    ]
    print(BalanceReport(specs).summarize())
