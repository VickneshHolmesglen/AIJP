class_name WaveSpawner
extends Node

signal wave_started(number: int)
signal wave_cleared(number: int, flawless: bool)

const WAVE_COOLDOWN_SEC := 12.0
const SPAWN_INTERVAL_SEC := 0.8

@export var enemy_scenes: Dictionary = {}

var current_wave: int = 0
var _waves: Array = []
var _alive: int = 0
var _leaked_this_wave: int = 0

func _ready() -> void:
	_waves = _load_waves("res://data/waves.json")
	EventBus.enemy_died.connect(_on_enemy_died)
	EventBus.enemy_leaked.connect(_on_enemy_leaked)

func _load_waves(path: String) -> Array:
	var file := FileAccess.open(path, FileAccess.READ)
	var parsed = JSON.parse_string(file.get_as_text())
	return parsed["waves"]

func start_wave() -> void:
	current_wave += 1
	_leaked_this_wave = 0
	wave_started.emit(current_wave)
	for entry in _waves[current_wave - 1]["enemies"]:
		for i in entry["count"]:
			_spawn_enemy(entry["kind"])
			await get_tree().create_timer(SPAWN_INTERVAL_SEC).timeout

func _spawn_enemy(kind: String) -> void:
	var enemy: Enemy = enemy_scenes[kind].instantiate()
	add_child(enemy)
	_alive += 1

func _on_enemy_died(_bounty: int) -> void:
	_alive -= 1
	_check_cleared()

func _on_enemy_leaked(_penalty: int) -> void:
	_alive -= 1
	_leaked_this_wave += 1
	_check_cleared()

func _check_cleared() -> void:
	if _alive == 0:
		wave_cleared.emit(current_wave, _leaked_this_wave == 0)
		await get_tree().create_timer(WAVE_COOLDOWN_SEC).timeout
		start_wave()
