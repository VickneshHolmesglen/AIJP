# Towers

Towers are the player's only way to stop enemies. Each tower is built on a build slot and can be
upgraded to level 3. The player may have at most 12 towers at once.

## Arrow Tower
The Arrow Tower fires single bolts at the closest enemy. Base damage is 12 and the fire rate is
1.5 shots per second. It costs 50 gold. Arrow bolts can hit flying enemies, which makes it the
cheapest answer to Wraiths.

## Frost Tower
The Frost Tower throws ice shards that apply the Chill effect. Chill slows an enemy by 30 percent
for 2 seconds. Base damage is only 6, so the Frost Tower is a support tower. It costs 80 gold.

## Venom Tower
The Venom Tower coats enemies in toxin and applies Poison. Damage on impact is 4. Most of its
value comes from the damage over time described in the status effects design. It costs 90 gold.

## Cannon Tower
The Cannon Tower lobs heavy shells with a splash radius of 96 pixels. Base damage is 40 but it
fires only 0.4 shots per second. Shells cannot hit flying enemies. It costs 120 gold and every
shell also applies Burn to enemies inside the blast.

## Upgrades and selling
Each upgrade level adds 25 percent to the tower's base damage. Upgrading to level N costs
0.75 times the base cost times N. Selling a tower refunds 60 percent of the total gold invested
in it, including upgrades. The refund is intentionally lossy to discourage constant rebuilding.
