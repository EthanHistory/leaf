extends CharacterBody3D
## Third-person player: mouse orbits the camera, WASD moves relative to the camera,
## Shift runs. Esc frees the mouse, left click captures it again.
##
## For screenshots, `-- --auto=walk|run` fakes holding W (and Shift for run).
## Screenshot and benchmark runs leave the mouse alone so camera angles are reproducible.

const WALK_SPEED := 1.25
const RUN_SPEED := 6.2  # FastRun at 1.25x: as fast as the stride allows without sliding
# Ground speed each clip covers on this character: Walk from the UAL root-motion
# clip, FastRun (Mixamo "Fast Run") from its hip travel. Playback is scaled by
# actual speed so the feet don't slide, capped so the stride doesn't look frantic.
const CLIP_SPEED := {"Walk": 0.99, "FastRun": 4.98}
const MAX_ANIM_SCALE := {"Walk": 1.5, "FastRun": 1.25}
const ACCEL := 10.0
const TURN_SPEED := 10.0
const SENSITIVITY := 0.0025
const CAM_DISTANCE := 4.8
const CAM_PITCH := -0.32  # looking slightly down at the player, as in the reference
const BLEND := 0.2

var model: Node3D
var anim: AnimationPlayer
var pivot: Node3D
var arm: SpringArm3D
var camera: Camera3D
var auto_mode := ""
var start_ms := 0


func _ready() -> void:
	start_ms = Time.get_ticks_msec()
	var scripted := false  # screenshot/benchmark runs: never grab the mouse
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--auto="):
			auto_mode = a.substr(7)
		if a.begins_with("--shot=") or a == "--bench":
			scripted = true

	var shape := CapsuleShape3D.new()
	shape.radius = 0.28
	shape.height = 1.7
	var col := CollisionShape3D.new()
	col.shape = shape
	col.position.y = 0.85
	add_child(col)

	model = load("res://assets/characters/female.glb").instantiate()
	add_child(model)
	_apply_materials()
	anim = model.find_children("*", "AnimationPlayer", true, false)[0]
	for n in ["Idle", "Walk", "FastRun"]:
		anim.get_animation(n).loop_mode = Animation.LOOP_LINEAR
	anim.play("Idle")

	pivot = Node3D.new()
	pivot.position.y = 1.45
	pivot.rotation.x = CAM_PITCH
	pivot.top_level = true
	# The pivot is moved every rendered frame in _process, so it must not be
	# physics-interpolated itself; it follows the player's interpolated position.
	pivot.physics_interpolation_mode = Node.PHYSICS_INTERPOLATION_MODE_OFF
	add_child(pivot)
	arm = SpringArm3D.new()
	arm.spring_length = CAM_DISTANCE
	arm.margin = 0.2
	arm.add_excluded_object(get_rid())
	pivot.add_child(arm)
	camera = Camera3D.new()
	camera.fov = 55.0
	camera.current = true
	arm.add_child(camera)

	if not scripted:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


## The Blender hair/eyebrow tints use nodes glTF can't carry, so set them here.
func _apply_materials() -> void:
	var hair := ShaderMaterial.new()
	hair.shader = load("res://shaders/hair.gdshader")
	var brow := StandardMaterial3D.new()
	brow.albedo_color = Color(0.32, 0.22, 0.14)
	var cap := StandardMaterial3D.new()
	cap.albedo_color = Color(0.36, 0.26, 0.17)
	cap.roughness = 0.6
	for mi in model.find_children("*", "MeshInstance3D", true, false):
		match String(mi.name):
			"Hair_New": mi.material_override = hair
			"Hair_Cap": mi.material_override = cap
			"Eyebrows": mi.material_override = brow


func _unhandled_input(event: InputEvent) -> void:
	# Skip the first moments after start: capturing the mouse warps it to the
	# window centre, and that jump would snap the camera to look straight down.
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED \
			and Time.get_ticks_msec() - start_ms > 300:
		pivot.rotation.y -= event.relative.x * SENSITIVITY
		pivot.rotation.x = clamp(pivot.rotation.x - event.relative.y * SENSITIVITY, -1.2, 0.35)
	elif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _physics_process(delta: float) -> void:
	var input := Vector2.ZERO
	if Input.is_key_pressed(KEY_W) or auto_mode != "": input.y -= 1
	if Input.is_key_pressed(KEY_S): input.y += 1
	if Input.is_key_pressed(KEY_A): input.x -= 1
	if Input.is_key_pressed(KEY_D): input.x += 1
	var running := Input.is_key_pressed(KEY_SHIFT) or auto_mode == "run"

	var yaw := Basis(Vector3.UP, pivot.rotation.y)
	var dir := yaw * Vector3(input.x, 0, input.y)
	dir = dir.normalized() if dir.length() > 0.01 else Vector3.ZERO
	var target := dir * (RUN_SPEED if running else WALK_SPEED)
	velocity.x = move_toward(velocity.x, target.x, ACCEL * delta * maxf(1.0, target.length()))
	velocity.z = move_toward(velocity.z, target.z, ACCEL * delta * maxf(1.0, target.length()))
	if not is_on_floor():
		velocity += get_gravity() * delta
	else:
		velocity.y = -0.5
	move_and_slide()

	# The model faces +Z; turn it smoothly toward the direction of travel.
	if dir != Vector3.ZERO:
		var want := atan2(dir.x, dir.z)
		model.rotation.y = lerp_angle(model.rotation.y, want, 1.0 - exp(-TURN_SPEED * delta))

	var speed := Vector2(velocity.x, velocity.z).length()
	var next := "Idle"
	if speed > (WALK_SPEED + RUN_SPEED) * 0.5:
		next = "FastRun"
	elif speed > 0.3:
		next = "Walk"
	if anim.current_animation != next:
		anim.play(next, BLEND)
	anim.speed_scale = clampf(speed / CLIP_SPEED[next], 0.8, MAX_ANIM_SCALE[next]) if CLIP_SPEED.has(next) else 1.0


func _process(delta: float) -> void:
	# Camera follows smoothly, so steps and slopes don't jolt the view. Movement
	# runs at the physics rate; following the interpolated position keeps the
	# character from juddering when the screen refreshes faster than that.
	var target := get_global_transform_interpolated().origin + Vector3.UP * 1.45
	pivot.global_position = pivot.global_position.lerp(target, 1.0 - exp(-12.0 * delta))
