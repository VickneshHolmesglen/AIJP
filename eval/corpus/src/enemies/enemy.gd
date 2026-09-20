class_name Enemy
extends CharacterBody2D

signal died(bounty: int)
signal enraged

const MIN_DAMAGE := 1
const POISON_MAX_STACKS := 3

@export var max_health: int = 60
@export var armor: int = 0
@export var bounty: int = 5
@export var move_speed: float = 80.0
@export var is_flying: bool = false

var health: int
var poison_stacks: int = 0
var poison_time_left: float = 0.0
var chill_time_left: float = 0.0
var _enraged := false

func _ready() -> void:
	health = max_health

# Applies incoming damage after armor reduction. Every hit deals at least MIN_DAMAGE.
func take_damage(raw_amount: int) -> void:
	var dealt = max(MIN_DAMAGE, raw_amount - armor)
	health -= dealt
	if health <= 0:
		died.emit(bounty)
		queue_free()
	elif not _enraged and health < max_health * 0.25 and is_boss():
		_enrage()

func apply_poison() -> void:
	# Poison ignores armor and refreshes its duration on every application.
	poison_stacks = min(poison_stacks + 1, POISON_MAX_STACKS)
	poison_time_left = 5.0

func apply_chill() -> void:
	if is_flying_immune_to_chill():
		return
	chill_time_left = 2.0

func is_flying_immune_to_chill() -> bool:
	return is_flying

func is_boss() -> bool:
	return max_health >= 5000

func _enrage() -> void:
	_enraged = true
	move_speed *= 1.5
	enraged.emit()

func _physics_process(delta: float) -> void:
	var speed := move_speed
	if chill_time_left > 0.0:
		speed *= 0.7
		chill_time_left -= delta
	velocity = path_direction() * speed
	move_and_slide()

func _process(delta: float) -> void:
	if poison_time_left > 0.0:
		poison_time_left -= delta
		health -= int(4 * poison_stacks * delta)
		if poison_time_left <= 0.0:
			poison_stacks = 0
