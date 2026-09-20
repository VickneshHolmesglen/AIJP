# Shardfall Architecture

Shardfall is a 2D tower defense game built with Godot 4 and GDScript.

## Project layout
Game code lives under `src/`. Enemy behaviour is in `src/enemies/enemy.gd`, tower behaviour in
`src/towers/tower.gd` and the wave logic in `src/systems/wave_spawner.gd`. Static tuning data is
kept outside the code: `data/waves.json` describes each wave and `config/game.yaml` holds the
global tuning constants.

## Global singletons
Two autoload singletons exist. `GameState` owns gold, lives and the current wave number. `EventBus`
is a signal-only node that lets systems talk without holding references to each other, for example
`EventBus.enemy_died` and `EventBus.wave_cleared`.

## Data flow of a hit
A tower calls `Enemy.take_damage` with the raw damage. The enemy subtracts its armor, clamps the
result to the minimum damage, reduces its health and emits `died` when health reaches zero. The
`died` signal carries the bounty, which `GameState` adds to the player's gold.

## Saving
Progress is saved by the `SaveManager` singleton, which serialises `GameState` to the file
`user://savegame.json` at the end of every wave. Saves are versioned so old files can be migrated.

## Balance tooling
`tools/balance.py` simulates waves offline. It estimates whether a tower setup can kill a wave
before the enemies reach the core and prints a balance report. Designers run it before changing
numbers in `config/game.yaml`.
