extends "res://leafling.gd"
## 잎사귀 전사 (Leaf warrior): a stocky plant warrior in a cloak of big leaves. It
## behaves like a leafling (idles, stomps about its patch, stops to look at the
## player), just bigger and heavier on its feet.
##
## The model and its Idle / Walk clips come from tools/build_leaf_warrior.py.

const WARRIOR := preload("res://assets/characters/leaf_warrior/leaf_warrior.glb")


func _init() -> void:
	scene = WARRIOR
	walk_speed = 0.5  # its stride covers about this at clip speed 1
	walk_anim_speed = 1.0
	tint = Color(0.88, 0.92, 0.84)
	space = 1.6
