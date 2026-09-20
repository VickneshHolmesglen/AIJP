# Enemies

Enemies walk along a fixed path from the spawn gate to the Shard Core. Any enemy that reaches the
core is a leak and costs the player lives.

## Grunt
The Grunt is the baseline enemy: 60 health, speed 80, no armor. Killing a Grunt pays a bounty of
5 gold.

## Runner
The Runner is fragile but fast: 35 health and speed 160. It pays a bounty of 8 gold. Runners are
designed to punish players who rely only on slow, high-damage towers.

## Brute
The Brute is a slow tank: 300 health, speed 45 and 8 armor. Armor subtracts from every incoming
hit, so cheap low-damage towers are nearly useless against it. The bounty is 25 gold.

## Wraith
The Wraith floats above the ground and is a flying enemy. It has 120 health and speed 100.
Wraiths are immune to Chill. Only towers that can target the air can hurt them. The bounty is
30 gold.

## Shardlord (boss)
The Shardlord is the boss. It has 5000 health and 15 armor and appears on waves 20 and 40. When
its health drops below 25 percent it enrages and gains 50 percent more movement speed. If a
Shardlord leaks it costs 5 lives instead of 1.

## Armor and minimum damage
Armor is subtracted flat from every hit. No hit ever deals less than 1 damage, so armor can slow
progress but never make an enemy invulnerable.
