extends Node3D
## 깻잎 몬스터 (Leafling): a little plant creature that potters about its home
## patch of the perilla forest. It stands idling (breathing, swaying its leaves,
## blinking, munching) for a while, then waddles to another spot nearby. When
## the player comes close it stops and turns to look at her.
##
## The model and its Idle / Walk clips come from tools/build_leafling.py.
## The level sets [member home], [member ground] and [member is_free] before
## adding it to the tree. leaf_warrior.gd reuses all this with its own model.

const MODEL := preload("res://assets/characters/leafling.glb")
const WALK_SPEED := 0.4  # m/s at scale 1
const WALK_ANIM_SPEED := 1.25
const TURN_SPEED := 4.0
const BLEND := 0.25
const NOTICE := 3.5  # metres: stops to look at the player inside this
const IDLE_TIME := Vector2(2.5, 7.0)
const SPACE := 0.9  # metres kept between leaflings
const SKIN_TINT := Color(0.8, 0.88, 0.72)

## Every leafling in the level, for keeping out of each other's way.
static var herd: Array = []
## The tuned copies of the imported materials, shared by all leaflings.
static var materials := {}

var home := Vector3.ZERO
var roam := 3.5  # wanders within this of home
## Ground height at (x, z).
var ground: Callable
## Whether a leafling may stand at (x, z).
var is_free: Callable
## The node it turns to look at when close (the player), if any.
var watch: Node3D

# Set in _init by kinds that extend this one.
var scene: PackedScene = MODEL
var walk_speed := WALK_SPEED
var walk_anim_speed := WALK_ANIM_SPEED
var tint := SKIN_TINT
var space := SPACE

var rng := RandomNumberGenerator.new()
var model: Node3D
var anim: AnimationPlayer
var target := Vector3.ZERO
var walking := false
var wait := 0.0


func _ready() -> void:
	rng.randomize()
	model = scene.instantiate()
	add_child(model)
	_tune_materials()
	anim = model.find_children("*", "AnimationPlayer", true, false)[0]
	for n in ["Idle", "Walk"]:
		anim.get_animation(n).loop_mode = Animation.LOOP_LINEAR
	# Out of step with each other: different start points and tempos.
	anim.play("Idle")
	anim.seek(rng.randf() * anim.current_animation_length, true)
	anim.speed_scale = rng.randf_range(0.9, 1.1)
	wait = rng.randf_range(0.0, IDLE_TIME.y)
	herd.append(self)


func _exit_tree() -> void:
	herd.erase(self)


## The Tripo textures have their lighting painted in and come out pale and glossy
## at roughness 0.5 next to the deep greens of the forest; a little darker and
## rougher, with a faint rim, they sit in its light.
func _tune_materials() -> void:
	for mi: MeshInstance3D in model.find_children("*", "MeshInstance3D", true, false):
		for i in mi.mesh.get_surface_count():
			var orig := mi.get_active_material(i) as StandardMaterial3D
			if not materials.has(orig):
				var mat := orig.duplicate() as StandardMaterial3D
				mat.roughness = 0.8
				mat.metallic_specular = 0.35
				mat.rim_enabled = true
				mat.rim = 0.15
				mat.rim_tint = 0.7
				if not orig.resource_name in ["Mouth", "Lash"]:
					mat.albedo_color *= tint
				if orig.resource_name.begins_with("eye"):
					mat.roughness = 0.15  # glossy eyes catch a highlight
					mat.metallic_specular = 0.7
					mat.rim_enabled = false
				materials[orig] = mat
			mi.set_surface_override_material(i, materials[orig])


func _physics_process(delta: float) -> void:
	var to_watch := INF
	if watch:
		to_watch = Vector2(watch.global_position.x - position.x, watch.global_position.z - position.z).length()
	if to_watch < NOTICE:
		walking = false
		wait = maxf(wait, 1.5)
		_face(watch.global_position, delta)
	elif walking:
		var to := Vector2(target.x - position.x, target.z - position.z)
		var step := walk_speed * scale.x * delta
		if to.length() <= step or _blocked():
			walking = false
			wait = rng.randf_range(IDLE_TIME.x, IDLE_TIME.y)
		else:
			_face(target, delta)
			# Walks the way it faces, so it curves round rather than sliding sideways.
			var fwd := Vector3(sin(rotation.y), 0.0, cos(rotation.y))
			position += fwd * step
	else:
		wait -= delta
		if wait <= 0.0:
			_pick_target()
	position.y = ground.call(position.x, position.z)

	var clip := "Walk" if walking else "Idle"
	if anim.current_animation != clip:
		anim.play(clip, BLEND)
	anim.speed_scale = walk_anim_speed if walking else 1.0


func _face(at: Vector3, delta: float) -> void:
	var yaw := atan2(at.x - position.x, at.z - position.z)
	rotation.y = lerp_angle(rotation.y, yaw, 1.0 - exp(-TURN_SPEED * delta))


func _pick_target() -> void:
	for i in 8:
		var a := rng.randf() * TAU
		var r := roam * sqrt(rng.randf())
		var p := home + Vector3(cos(a) * r, 0.0, sin(a) * r)
		var mid := (position + p) * 0.5
		if is_free.call(p.x, p.z) and is_free.call(mid.x, mid.z) and _room_at(p):
			target = p
			walking = true
			return
	wait = 1.0


## Whether no other leafling stands or is heading too near [param p].
func _room_at(p: Vector3) -> bool:
	for o in herd:
		if o == self:
			continue
		var gap: float = (space + o.space) * 0.5
		if Vector2(p.x - o.position.x, p.z - o.position.z).length() < gap:
			return false
		if o.walking and Vector2(p.x - o.target.x, p.z - o.target.z).length() < gap:
			return false
	return true


## Whether another leafling is just ahead.
func _blocked() -> bool:
	var fwd := Vector2(sin(rotation.y), cos(rotation.y))
	for o in herd:
		if o == self:
			continue
		var d := Vector2(o.position.x - position.x, o.position.z - position.z)
		if d.length() < (space + o.space) * 0.4 and d.dot(fwd) > 0.0:
			return true
	return false
