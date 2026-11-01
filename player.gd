extends CharacterBody3D
## Third-person player: mouse orbits the camera, WASD moves relative to the camera,
## Shift runs, R draws or stows the axe and shield. Esc frees the mouse, left
## click captures it again.
##
## For screenshots, `-- --auto=walk|run` fakes holding W (and Shift for run).
## Screenshot and benchmark runs leave the mouse alone so camera angles are reproducible.

const WALK_SPEED := 1.25
const RUN_SPEED := 5.3  # run at 1.25x: as fast as the stride allows without sliding
const MODEL_HEIGHT := 1.7  # the heroine .glb is ~1.0 m tall; scale it to fit the capsule
const MODEL_SCALE := MODEL_HEIGHT / 1.0
# Ground speed each clip covers at MODEL_SCALE, from the hip travel of its root
# motion. Playback is scaled by actual speed so the feet don't slide, capped so
# the stride doesn't look frantic.
const CLIP_SPEED := {"walk": 0.692 * MODEL_SCALE, "run": 2.52 * MODEL_SCALE}
const MAX_ANIM_SCALE := {"walk": 1.5, "run": 1.25}
const ACCEL := 10.0
const TURN_SPEED := 10.0
const SENSITIVITY := 0.0025
const CAM_DISTANCE := 4.8
const CAM_PITCH := -0.32  # looking slightly down at the player, as in the reference
const BLEND := 0.2
# Hair spring bones (chains built by tools/build_heroine.py). Lengths are in the
# model's own units, before MODEL_SCALE.
const HAIR_STIFFNESS := 0.5
const HAIR_DRAG := 0.35
const HAIR_GRAVITY := 0.6
const HAIR_RADIUS := 0.012
const WIND := Vector3(0.12, 0.0, 0.05)  # breeze the hair drifts in
const AIRFLOW := 0.15  # headwind from moving, per m/s: streams the hair out behind
# Gear (assets/gear, built by tools/build_gear.py). R draws or stows it: the
# hands reach for it by IK, take it, and swing back. Times in seconds.
const REACH_TIME := 0.35
const RETURN_TIME := 0.4
const SETTLE_TIME := 0.25  # gear glides from where it was taken into its new mount
# Where the gear sits when stowed, in the model's rest pose and units (before
# MODEL_SCALE): shield slung on the back, axe at the right hip.
const BACK_MOUNT := Vector3(0.0, 0.7, -0.06)
const BACK_ROLL := 0.25  # radians the slung shield leans, top towards her left
const HIP_MOUNT := Vector3(-0.115, 0.43, -0.01)
const HIP_TILT := 0.3  # radians the haft leans, head forward
# Where the hands take hold of the stowed gear, in the gear's own metres.
const SHIELD_HANDLE := Vector3(-0.16, 0.2, 0.0)
const AXE_HANDLE := Vector3(0.0, 0.0, 0.0)

var model: Node3D
var anim: AnimationPlayer
var pivot: Node3D
var arm: SpringArm3D
var camera: Camera3D
var hair: SpringBoneSimulator3D
var auto_mode := ""
var start_ms := 0
var skel: Skeleton3D
var axe: Node3D
var shield: Node3D
var arm_ik: TwoBoneIK3D
# Per gear piece: {node, stowed: BoneAttachment3D, held: BoneAttachment3D,
# stowed_mount, held_mount: Transform3D, handle: Node3D}.
var gear: Array[Dictionary] = []
var drawn := false
var swapping := false


func _ready() -> void:
	start_ms = Time.get_ticks_msec()
	var scripted := false  # screenshot/benchmark runs: never grab the mouse
	var gear_mode := ""
	var view := NAN
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--auto="):
			auto_mode = a.substr(7)
		if a.begins_with("--gear="):
			gear_mode = a.substr(7)
		if a.begins_with("--view="):
			view = deg_to_rad(float(a.substr(7)))
		if a.begins_with("--shot=") or a == "--bench":
			scripted = true

	var shape := CapsuleShape3D.new()
	shape.radius = 0.28
	shape.height = 1.7
	var col := CollisionShape3D.new()
	col.shape = shape
	col.position.y = 0.85
	add_child(col)

	model = load("res://assets/characters/heroine.glb").instantiate()
	model.scale = Vector3.ONE * MODEL_SCALE
	add_child(model)
	skel = model.find_children("*", "Skeleton3D", true, false)[0]
	_tune_material()
	_add_hair_physics()
	_add_gear()
	anim = model.find_children("*", "AnimationPlayer", true, false)[0]
	for n in ["idle", "walk", "run"]:
		var a := anim.get_animation(n)
		a.loop_mode = Animation.LOOP_LINEAR
		_strip_root_motion(a)
	anim.play("idle")

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

	# Screenshot aids: `--gear=drawn` starts with the gear in hand, `--gear=draw`
	# draws it straight away, `--gear=stow` puts it away; `--view=DEG` swings the
	# camera round her, close up.
	if gear_mode == "drawn" or gear_mode == "stow":
		_set_drawn(true)
	if gear_mode == "draw" or gear_mode == "stow":
		toggle_gear.call_deferred()
	if not is_nan(view):
		pivot.rotation.y = view
		arm.spring_length = 1.9

	if not scripted:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


## Tripo exports one fully matte material (roughness 0.9) for skin, hair and
## clothes, which reads as clay. A baked roughness map (tools/bake_heroine_roughness.py)
## gives each its own sheen, and a rim makes the silhouette and face stand out. (Screen-space subsurface scattering was tried and dropped:
## it blurs the painted eyes and brows.)
func _tune_material() -> void:
	for mi in model.find_children("*", "MeshInstance3D", true, false):
		var mat := (mi as MeshInstance3D).get_active_material(0) as StandardMaterial3D
		if mat == null:
			continue
		mat = mat.duplicate()
		if mi.name == "Hair":
			mat.roughness = 0.38
		else:
			mat.roughness = 1.0  # scales the map
			mat.roughness_texture = load("res://assets/characters/heroine_roughness.png")
			mat.roughness_texture_channel = BaseMaterial3D.TEXTURE_CHANNEL_RED
		mat.metallic_specular = 0.4
		mat.rim_enabled = true
		mat.rim = 0.2
		mat.rim_tint = 0.6
		mat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
		mi.material_override = mat


## Swings the hair chains with a spring simulation, so the hair bounces with her
## stride, streams out behind when she runs and drifts in the wind. The
## head and torso are collision shapes the hair slides over.
func _add_hair_physics() -> void:
	var skel: Skeleton3D = model.find_children("*", "Skeleton3D", true, false)[0]
	var chains: Array[String] = []
	for b in skel.get_bone_count():
		var n := skel.get_bone_name(b)
		if n.begins_with("hair_") and n.ends_with("_0"):
			chains.append(n.trim_suffix("_0"))
	hair = SpringBoneSimulator3D.new()
	hair.setting_count = chains.size()
	for i in chains.size():
		var last := 0
		while skel.find_bone("%s_%d" % [chains[i], last + 1]) >= 0:
			last += 1
		hair.set_root_bone_name(i, chains[i] + "_0")
		hair.set_end_bone_name(i, "%s_%d" % [chains[i], last])
		hair.set_extend_end_bone(i, true)
		hair.set_end_bone_length(i, 0.03)
		hair.set_stiffness(i, HAIR_STIFFNESS)
		hair.set_drag(i, HAIR_DRAG)
		hair.set_gravity(i, HAIR_GRAVITY)
		hair.set_radius(i, HAIR_RADIUS * MODEL_SCALE)
	skel.add_child(hair)
	# Simulate in the player's space rather than the world's: the body moves in
	# physics ticks, and the hair would whip at every tick's jump. The player
	# node neither turns nor scales, so "down" is still down; the run is felt
	# through AIRFLOW instead.
	for i in chains.size():
		hair.set_center_from(i, SpringBoneSimulator3D.CENTER_FROM_NODE)
		hair.set_center_node(i, hair.get_path_to(self))
	_add_hair_collider("mixamorig_Head", Vector3(0, 0.045, 0.005), 0.062, 0.0)
	_add_hair_collider("mixamorig_Neck", Vector3(0, 0.02, 0), 0.035, 0.0)
	_add_hair_collider("mixamorig_Spine2", Vector3(0, 0.0, -0.01), 0.058, 0.2)
	_add_hair_collider("mixamorig_LeftShoulder", Vector3(0, 0.06, 0), 0.026, 0.0)
	_add_hair_collider("mixamorig_RightShoulder", Vector3(0, 0.06, 0), 0.026, 0.0)


## A sphere, or a capsule along the bone when [param height] > 0.
func _add_hair_collider(bone: String, offset: Vector3, radius: float, height: float) -> void:
	var c: SpringBoneCollision3D
	if height > 0.0:
		var cap := SpringBoneCollisionCapsule3D.new()
		cap.radius = radius * MODEL_SCALE
		cap.height = height * MODEL_SCALE
		c = cap
	else:
		var sph := SpringBoneCollisionSphere3D.new()
		sph.radius = radius * MODEL_SCALE
		c = sph
	c.bone_name = bone
	c.position_offset = offset * MODEL_SCALE
	hair.add_child(c)


## Hangs the shield on her back and the axe at her hip, works out where each
## sits in hand, and sets up the arm IK that reaches for them. Mounts are worked
## out in the rest pose from the bones themselves, so they ride on whatever
## the bone axes happen to be.
func _add_gear() -> void:
	axe = load("res://assets/gear/axe.glb").instantiate()
	shield = load("res://assets/gear/shield.glb").instantiate()

	var back := _mount(Vector3(sin(BACK_ROLL), cos(BACK_ROLL), 0), Vector3(0, 0, -1), BACK_MOUNT)
	var hip := _mount(Vector3(0, cos(HIP_TILT), sin(HIP_TILT)), Vector3(0, 0, 1), HIP_MOUNT)

	# In hand. The hand bones give the finger direction and, from index to
	# pinky, the knuckle line; the palm faces across both.
	var r_fingers := (_rest("RightHandMiddle1") - _rest("RightHand")).normalized()
	var r_knuckles := (_rest("RightHandIndex1") - _rest("RightHandPinky1")).normalized()
	var r_palm := r_knuckles.cross(r_fingers)
	# The haft runs across the palm from the heel of the hand up past the index
	# finger, head above the thumb and edge facing the way the knuckles do.
	var axe_held := _mount(r_knuckles + r_fingers * 0.3, r_fingers,
			_rest("RightHandMiddle1") + r_palm * 0.012 - r_fingers * 0.004)
	# The shield is strapped to the outside of the forearm, top towards the elbow.
	var l_fingers := (_rest("LeftHandMiddle1") - _rest("LeftHand")).normalized()
	var l_knuckles := (_rest("LeftHandIndex1") - _rest("LeftHandPinky1")).normalized()
	var l_back := l_knuckles.cross(l_fingers)
	var elbow := _rest("LeftForeArm")
	var wrist := _rest("LeftHand")
	var shield_held := _mount(elbow - wrist, l_back, elbow.lerp(wrist, 0.55) + l_back * 0.022)

	gear = [
		_gear_piece(shield, "Spine2", back, "LeftForeArm", shield_held, SHIELD_HANDLE),
		_gear_piece(axe, "Hips", hip, "RightHand", axe_held, AXE_HANDLE),
	]
	_set_drawn(false)

	# Elbows: out and up when reaching over the shoulder for the shield, out
	# and back when reaching down for the axe.
	arm_ik = TwoBoneIK3D.new()
	arm_ik.setting_count = 2
	arm_ik.influence = 0.0
	arm_ik.active = false
	skel.add_child(arm_ik)
	for i in 2:
		var side := "Left" if i == 0 else "Right"
		var pole := Node3D.new()
		pole.position = Vector3(0.35, 0.95, 0.1) if i == 0 else Vector3(-0.4, 0.65, -0.25)
		skel.add_child(pole)
		arm_ik.set_root_bone_name(i, "mixamorig_%sArm" % side)
		arm_ik.set_middle_bone_name(i, "mixamorig_%sForeArm" % side)
		arm_ik.set_end_bone_name(i, "mixamorig_%sHand" % side)
		arm_ik.set_target_node(i, arm_ik.get_path_to(gear[i].handle))
		arm_ik.set_pole_node(i, arm_ik.get_path_to(pole))


func _rest(bone: String) -> Vector3:
	return skel.get_bone_global_rest(skel.find_bone("mixamorig_" + bone)).origin


## A gear frame in model space: haft or top along [param up], edge or boss
## towards [param front], scaled from the gear's metres to the model's units.
func _mount(up: Vector3, front: Vector3, origin: Vector3) -> Transform3D:
	var y := up.normalized()
	var z := (front - y * y.dot(front)).normalized()
	return Transform3D(Basis(y.cross(z), y, z).scaled(Vector3.ONE / MODEL_SCALE), origin)


func _gear_piece(node: Node3D, stowed_bone: String, stowed: Transform3D,
		held_bone: String, held: Transform3D, handle: Vector3) -> Dictionary:
	var g := {"node": node}
	for k in [["stowed", stowed_bone, stowed], ["held", held_bone, held]]:
		var att := BoneAttachment3D.new()
		att.bone_name = "mixamorig_" + k[1]
		skel.add_child(att)
		g[k[0]] = att
		# From model space into the bone's own frame.
		g[k[0] + "_mount"] = skel.get_bone_global_rest(skel.find_bone(att.bone_name)).affine_inverse() * k[2]
	# What the hand reaches for, riding on the stowed mount.
	g.handle = Node3D.new()
	g.handle.position = g.stowed_mount * handle
	g.stowed.add_child(g.handle)
	return g


func toggle_gear() -> void:
	if swapping:
		return
	swapping = true
	arm_ik.active = true
	var tw := create_tween().set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	tw.tween_property(arm_ik, "influence", 1.0, REACH_TIME)
	tw.tween_callback(_set_drawn.bind(not drawn, true))
	tw.tween_property(arm_ik, "influence", 0.0, RETURN_TIME)
	tw.tween_callback(_end_swap)


func _end_swap() -> void:
	arm_ik.active = false
	swapping = false


## Moves the gear into the hands or back to where it is stowed. With
## [param glide] it slides there from wherever it is instead of jumping.
func _set_drawn(on: bool, glide := false) -> void:
	drawn = on
	for g in gear:
		var node: Node3D = g.node
		var mount: Transform3D = g.held_mount if on else g.stowed_mount
		if node.get_parent():
			node.reparent(g.held if on else g.stowed)
		else:
			g.stowed.add_child(node)
		if glide:
			create_tween().set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT) \
					.tween_property(node, "transform", mount, SETTLE_TIME)
		else:
			node.transform = mount


## The heroine clips carry root motion (the hips travel forward along Z), which
## would pull the model away from the capsule and snap it back each loop. Pin the
## hips' Z to their rest position so the clips play in place. (Not to the first
## key: the run clip starts 0.57 m forward, which put her a metre ahead of the
## capsule while running.)
func _strip_root_motion(a: Animation) -> void:
	var skel: Skeleton3D = model.find_children("*", "Skeleton3D", true, false)[0]
	var z0 := skel.get_bone_rest(skel.find_bone("mixamorig_Hips")).origin.z
	for t in a.get_track_count():
		if a.track_get_type(t) == Animation.TYPE_POSITION_3D \
				and String(a.track_get_path(t)).ends_with(":mixamorig_Hips"):
			for k in a.track_get_key_count(t):
				var p: Vector3 = a.track_get_key_value(t, k)
				a.track_set_key_value(t, k, Vector3(p.x, p.y, z0))


func _unhandled_input(event: InputEvent) -> void:
	# Skip the first moments after start: capturing the mouse warps it to the
	# window centre, and that jump would snap the camera to look straight down.
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED \
			and Time.get_ticks_msec() - start_ms > 300:
		pivot.rotation.y -= event.relative.x * SENSITIVITY
		pivot.rotation.x = clamp(pivot.rotation.x - event.relative.y * SENSITIVITY, -1.2, 0.35)
	elif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_R:
		toggle_gear()
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
	var next := "idle"
	if speed > (WALK_SPEED + RUN_SPEED) * 0.5:
		next = "run"
	elif speed > 0.3:
		next = "walk"
	if anim.current_animation != next:
		anim.play(next, BLEND)
	anim.speed_scale = clampf(speed / CLIP_SPEED[next], 0.8, MAX_ANIM_SCALE[next]) if CLIP_SPEED.has(next) else 1.0


func _process(delta: float) -> void:
	# Gusting breeze: a steady push plus two slow, out-of-step waves.
	var t := Time.get_ticks_msec() / 1000.0
	var gust := 0.5 + 0.3 * sin(t * 1.3) + 0.2 * sin(t * 3.1 + 1.7)
	hair.external_force = WIND * gust - Vector3(velocity.x, 0.0, velocity.z) * AIRFLOW

	# Camera follows smoothly, so steps and slopes don't jolt the view. Movement
	# runs at the physics rate; following the interpolated position keeps the
	# character from juddering when the screen refreshes faster than that.
	var target := get_global_transform_interpolated().origin + Vector3.UP * 1.45
	pivot.global_position = pivot.global_position.lerp(target, 1.0 - exp(-12.0 * delta))
