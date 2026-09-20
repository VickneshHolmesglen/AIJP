class_name Tower
extends Node2D

signal upgraded(level: int)

const MAX_LEVEL := 3
const SELL_REFUND_RATIO := 0.6

@export var base_cost: int = 50
@export var base_damage: int = 12
@export var fire_rate: float = 1.5
@export var targets_air: bool = true

var level: int = 1
var total_invested: int = 0
var _cooldown := 0.0

func _ready() -> void:
	total_invested = base_cost

# Damage grows by 25 percent of base damage per level above 1.
func current_damage() -> int:
	return int(base_damage * (1.0 + 0.25 * (level - 1)))

func upgrade_cost() -> int:
	return int(base_cost * 0.75 * (level + 1))

func upgrade() -> bool:
	if level >= MAX_LEVEL:
		return false
	var cost := upgrade_cost()
	if not GameState.spend_gold(cost):
		return false
	level += 1
	total_invested += cost
	upgraded.emit(level)
	return true

func sell_value() -> int:
	return int(total_invested * SELL_REFUND_RATIO)

func find_target() -> Enemy:
	var best: Enemy = null
	for enemy in get_tree().get_nodes_in_group("enemies"):
		if enemy.is_flying and not targets_air:
			continue
		if best == null or enemy.global_position.distance_to(global_position) > best.global_position.distance_to(global_position):
			best = enemy
	return best

func _process(delta: float) -> void:
	_cooldown -= delta
	if _cooldown > 0.0:
		return
	var target := find_target()
	if target:
		target.take_damage(current_damage())
		_cooldown = 1.0 / fire_rate
