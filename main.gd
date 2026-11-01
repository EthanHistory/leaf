extends Node3D
## Builds the forest stream test scene at startup from the Blender assets and
## the Quaternius Stylized Nature MegaKit (CC0, assets/vendor/megakit).
##
## Screenshot mode:  godot --path . -- --shot=out.png [--cam=top] [--frames=150]
## `--cam=portrait` frames the player's face from the front, for checking the character.

const WATER_Y := -0.2
const BRIDGE_Z := -19.0
const HOUSE_Z := -26.0
const HOUSE_OFFSET := 8.0
const HOUSE_SCALE := 1.6
const HOUSE_YAW := -20.0
# Half-width of the strip under the rope bridge that stays free of rocks and pads.
const BRIDGE_CLEAR := 2.8
const CAMERA_Z := 10.0
# House footprints in model space: [half width along x, back z, front z]. The ground
# under every footprint is levelled by PLOTS in tools/build_assets.py; keep in sync.
const HOUSE_FOOTPRINT := [3.0, -3.0, 3.1]
# Generated cottages (tools/build_houses.py) forming a hamlet around the main house:
# [name, offset from the stream centre, z, yaw in degrees, footprint...].
const VILLAGE := [
	["hut_orange", 19.0, -17.5, -75.0, 2.4, -2.3, 3.6],
	["tall_teal", 20.0, -30.5, -65.0, 2.7, -2.6, 2.6],
	["cottage_blue", -22.5, -29.0, 60.0, 3.3, -2.9, 4.3],
	["longhouse_purple", 12.0, -41.5, -10.0, 4.3, -3.0, 4.3],
	["townhouse_green", -10.0, -26.0, 55.0, 3.0, -2.8, 2.8],
	["cottage_red", -11.5, -38.0, 70.0, 3.2, -2.9, 4.2],
]
const VILLAGE_SCALE := 1.15

var rng := RandomNumberGenerator.new()
var noise_tex: NoiseTexture2D
var camera: Camera3D
var shot_path := ""
var shot_frames := 150
var cam_mode := "main"
var bench := false
var vendor_cache := {}
var player: CharacterBody3D
var env: Environment
var sun: DirectionalLight3D
# Benchmark A/B: `--off=fog,ssao,dof,glow,shadows,msaa,fxaa,grass,water,treeshadow`
# disables those features.
var off: PackedStringArray = []


# Keep in sync with tools/build_assets.py.
static func river_cx(z: float) -> float:
	return 1.2 * sin(z * 0.12) + 0.5 * sin(z * 0.31 + 1.0)


static func river_w(z: float) -> float:
	return 3.0 + 0.6 * sin(z * 0.2 + 2.0)


static func house_xz() -> Vector2:
	return Vector2(river_cx(HOUSE_Z) + HOUSE_OFFSET, HOUSE_Z)


## True within [param margin] metres of a house footprint.
static func on_plot(x: float, z: float, margin: float) -> bool:
	var h := house_xz()
	if _in_footprint(x - h.x, z - h.y, HOUSE_YAW, HOUSE_SCALE, HOUSE_FOOTPRINT, margin):
		return true
	for v in VILLAGE:
		if _in_footprint(x - river_cx(v[2]) - v[1], z - v[2], v[3], VILLAGE_SCALE, v.slice(4), margin):
			return true
	return false


static func _in_footprint(dx: float, dz: float, yaw: float, s: float, fp: Array, margin: float) -> bool:
	var a := deg_to_rad(yaw)
	var lx := (cos(a) * dx - sin(a) * dz) / s
	var lz := (sin(a) * dx + cos(a) * dz) / s
	var m := margin / s
	return absf(lx) < fp[0] + m and lz > fp[1] - m and lz < fp[2] + m


## True where vegetation would bury the house or the bridge. With [param sightline],
## also keeps the line of sight from the camera to the house open.
static func in_clearing(x: float, z: float, margin: float, sightline: bool) -> bool:
	var p := Vector2(x, z)
	var house := house_xz()
	if p.distance_to(house) < 8.0 + margin:
		return true
	if on_plot(x, z, maxf(margin + 1.5, 0.3)):
		return true
	if absf(z - BRIDGE_Z) < 2.0 + margin and absf(x - river_cx(BRIDGE_Z)) < 6.0 + margin:
		return true
	if sightline:
		var cam := Vector2(river_cx(CAMERA_Z) + 0.4, CAMERA_Z)
		var closest := Geometry2D.get_closest_point_to_segment(p, cam, house)
		if p.distance_to(closest) < 8.0 and z < -6.0:
			return true
	return false


func _ready() -> void:
	rng.seed = 7
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--shot="):
			shot_path = arg.substr(7)
		elif arg.begins_with("--frames="):
			shot_frames = int(arg.substr(9))
		elif arg.begins_with("--cam="):
			cam_mode = arg.substr(6)
		elif arg == "--bench":
			bench = true
		elif arg.begins_with("--off="):
			off = arg.substr(6).split(",")

	noise_tex = _noise(256, 0.02, false)
	_setup_environment()
	_setup_camera()
	add_child(load("res://assets/terrain.glb").instantiate())
	_apply_material(self, "Terrain", _shader_mat("terrain"))
	# Ground raycasts need the terrain collider registered with the physics server.
	await get_tree().physics_frame
	await get_tree().physics_frame

	if not off.has("water"):
		_add_water()
	_add_trees()
	_add_props()
	_scatter_rocks()
	if not off.has("grass"):
		_scatter_grass()
	_scatter_pads()
	if cam_mode == "main" or cam_mode == "portrait":
		_add_player()

	if bench:
		_run_benchmark()
	elif shot_path != "":
		_take_screenshot()


# ---------------------------------------------------------------- helpers

func _noise(size: int, freq: float, as_normal: bool) -> NoiseTexture2D:
	var fn := FastNoiseLite.new()
	fn.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	fn.frequency = freq
	fn.fractal_octaves = 4
	var tex := NoiseTexture2D.new()
	tex.width = size
	tex.height = size
	tex.seamless = true
	tex.noise = fn
	if as_normal:
		tex.as_normal_map = true
		tex.bump_strength = 6.0
	return tex


func _shader_mat(name: String) -> ShaderMaterial:
	var m := ShaderMaterial.new()
	m.shader = load("res://shaders/%s.gdshader" % name)
	m.set_shader_parameter("noise_tex", noise_tex)
	return m


func _std_mat(color: Color, roughness := 0.85) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = color
	m.albedo_texture = noise_tex
	m.uv1_triplanar = true
	m.uv1_scale = Vector3.ONE * 0.6
	m.roughness = roughness
	return m


func _apply_material(root: Node, mesh_name: String, mat: Material) -> void:
	var mi := root.find_child(mesh_name, true, false) as MeshInstance3D
	mi.material_override = mat


func _meshes(path: String) -> Dictionary:
	var scene := load(path).instantiate() as Node
	var out := {}
	for mi in scene.find_children("*", "MeshInstance3D", true, false):
		out[String(mi.name)] = (mi as MeshInstance3D).mesh
	scene.free()
	return out


## Loads a Quaternius MegaKit mesh with its leaf and grass materials swapped for
## the wind shader. Bark keeps its imported material.
func _vendor(name: String, sway: float, up_normals := false) -> Mesh:
	var key := "%s/%s/%s" % [name, sway, up_normals]
	if vendor_cache.has(key):
		return vendor_cache[key]
	var scene := load("res://assets/vendor/megakit/glTF/%s.gltf" % name).instantiate() as Node
	var mi := scene.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D
	var mesh := mi.mesh.duplicate() as ArrayMesh
	var mats: Array[Material] = []
	for i in mesh.get_surface_count():
		mats.append(mi.get_active_material(i))
	scene.free()

	var height := mesh.get_aabb().end.y
	for i in mats.size():
		var orig := mats[i] as BaseMaterial3D
		if orig == null or orig.resource_name.begins_with("Bark"):
			continue
		var m := ShaderMaterial.new()
		m.shader = load("res://shaders/vendor_foliage.gdshader")
		m.set_shader_parameter("albedo_tex", orig.albedo_texture)
		var tint := orig.albedo_color
		if orig.resource_name == "Grass":
			# The pack's grass is quite yellow; pull it toward the reference greens.
			tint *= Color(0.82, 1.0, 0.7)
		m.set_shader_parameter("tint", tint)
		m.set_shader_parameter("sway", sway)
		m.set_shader_parameter("sway_height", height)
		m.set_shader_parameter("up_normals", up_normals)
		m.set_shader_parameter("recolor", orig.resource_name.begins_with("Leaves_"))
		mesh.surface_set_material(i, m)
	vendor_cache[key] = mesh
	return mesh


func _instance(path: String, xform: Transform3D) -> Node3D:
	var node := load(path).instantiate() as Node3D
	node.transform = xform
	return node


func _random_xform(x: float, z: float, s: float, sink := 0.0) -> Transform3D:
	var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3.ONE * s)
	return Transform3D(b, Vector3(x, _ground_y(x, z) - sink, z))


func _ground_y(x: float, z: float) -> float:
	var q := PhysicsRayQueryParameters3D.create(Vector3(x, 50.0, z), Vector3(x, -50.0, z))
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	return hit.position.y if hit else 0.0


func _add_mesh(mesh: Mesh, mat: Material, xform: Transform3D, shadows := true) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = mat
	mi.transform = xform
	if not shadows:
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(mi)
	return mi


## Instances [param mesh] at [param xforms]. With [param chunk] > 0 the instances are
## split into a grid of [param chunk]-sized cells, one node each, so the renderer can
## frustum- and shadow-cull them; [param vis_end] > 0 also hides cells beyond that distance.
func _multimesh(mesh: Mesh, mat: Material, xforms: Array[Transform3D], shadows: bool,
		chunk := 0.0, vis_end := 0.0) -> void:
	var cells := {}
	for t in xforms:
		var key := Vector2i(floori(t.origin.x / chunk), floori(t.origin.z / chunk)) if chunk > 0.0 else Vector2i.ZERO
		if not cells.has(key):
			cells[key] = [] as Array[Transform3D]
		cells[key].append(t)
	for key in cells:
		var cell: Array[Transform3D] = cells[key]
		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.mesh = mesh
		mm.instance_count = cell.size()
		for i in cell.size():
			mm.set_instance_transform(i, cell[i])
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		mmi.material_override = mat
		if not shadows:
			mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		if vis_end > 0.0:
			mmi.visibility_range_end = vis_end
			mmi.visibility_range_end_margin = 4.0
		add_child(mmi)


# ---------------------------------------------------------------- scene

func _setup_environment() -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.32, 0.58, 0.92)
	sky_mat.sky_horizon_color = Color(0.78, 0.87, 0.92)
	sky_mat.ground_horizon_color = Color(0.6, 0.7, 0.55)
	sky_mat.ground_bottom_color = Color(0.25, 0.32, 0.18)
	var sky := Sky.new()
	sky.sky_material = sky_mat

	env = Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.95
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.tonemap_exposure = 1.1
	env.ssao_enabled = true
	env.ssao_intensity = 1.5
	env.sdfgi_enabled = false
	env.glow_enabled = true
	env.glow_intensity = 0.7
	env.glow_bloom = 0.08
	env.glow_hdr_threshold = 0.9
	env.volumetric_fog_enabled = true
	env.volumetric_fog_density = 0.003
	env.volumetric_fog_albedo = Color(0.9, 0.95, 0.85)
	env.volumetric_fog_anisotropy = 0.6
	env.adjustment_enabled = true
	env.adjustment_saturation = 1.2
	env.adjustment_contrast = 1.05

	var attrs := CameraAttributesPractical.new()
	attrs.dof_blur_far_enabled = true
	attrs.dof_blur_far_distance = 40.0
	attrs.dof_blur_far_transition = 20.0
	attrs.dof_blur_amount = 0.06

	var we := WorldEnvironment.new()
	we.environment = env
	we.camera_attributes = attrs
	add_child(we)

	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42.0, 150.0, 0.0)
	sun.light_color = Color(1.0, 0.94, 0.82)
	sun.light_energy = 2.3
	sun.shadow_enabled = true
	# Shadow rendering dominated GPU time (~13 of 23 ms) and swung with the view
	# heading, since every tree and bush in the cascades is redrawn per split.
	# Two splits over a shorter range keep the near shadows that matter.
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	sun.directional_shadow_max_distance = 32.0
	sun.light_volumetric_fog_energy = 1.5
	add_child(sun)

	env.volumetric_fog_enabled = env.volumetric_fog_enabled and not off.has("fog")
	env.ssao_enabled = env.ssao_enabled and not off.has("ssao")
	env.glow_enabled = env.glow_enabled and not off.has("glow")
	attrs.dof_blur_far_enabled = not off.has("dof")
	sun.shadow_enabled = not off.has("shadows")
	if off.has("msaa"):
		get_viewport().msaa_3d = Viewport.MSAA_DISABLED
	if off.has("fxaa"):
		get_viewport().screen_space_aa = Viewport.SCREEN_SPACE_AA_DISABLED


func _setup_camera() -> void:
	# The default mode is third-person play; the player brings its own camera.
	if cam_mode == "main" or cam_mode == "portrait":
		return
	camera = Camera3D.new()
	camera.set_script(load("res://fly_camera.gd"))
	camera.fov = 60.0
	add_child(camera)
	if cam_mode == "village":
		camera.position = Vector3(river_cx(-14.0) + 2.0, 6.0, -14.0)
		camera.look_at(Vector3(river_cx(-34.0) + 3.0, 1.0, -34.0))
	elif cam_mode == "near":
		camera.position = Vector3(river_cx(-11.0) - 1.0, 2.2, -11.0)
		camera.look_at(Vector3(river_cx(BRIDGE_Z) + 2.0, 0.8, BRIDGE_Z - 2.0))
	elif cam_mode == "top":
		camera.position = Vector3(0, 60, -14)
		camera.look_at(Vector3(0, 0, -14.01))
	else:  # "fly": the original overview shot
		camera.position = Vector3(river_cx(CAMERA_Z) + 0.4, 4.2, CAMERA_Z)
		camera.look_at(Vector3(river_cx(-12.0), 0.2, -12.0))


func _add_water() -> void:
	var plane := PlaneMesh.new()
	plane.size = Vector2(64, 64)
	plane.subdivide_width = 4
	plane.subdivide_depth = 4
	var mat := _shader_mat("water")
	mat.set_shader_parameter("normal_a", _noise(512, 0.03, true))
	mat.set_shader_parameter("normal_b", _noise(512, 0.05, true))
	mat.set_shader_parameter("foam_noise", _noise(256, 0.04, false))
	_add_mesh(plane, mat, Transform3D(Basis(), Vector3(0, WATER_Y, -16)), false)


func _add_trees() -> void:
	# Hero: a big twisted tree on the left bank, its crown reaching over the stream.
	var hx := river_cx(2.0) - 6.2
	var hb := Basis(Vector3.UP, deg_to_rad(-25.0)).scaled(Vector3.ONE * 0.5)
	_add_mesh(_vendor("TwistedTree_1", 0.15), null, Transform3D(hb, Vector3(hx, _ground_y(hx, 2.0) - 0.1, 2.0)))

	var names := ["CommonTree_1", "CommonTree_2", "CommonTree_3", "CommonTree_4", "CommonTree_5"]
	var per_variant: Array = []
	for n in names:
		per_variant.append([] as Array[Transform3D])
	var placed := 0
	var tries := 0
	while placed < 150 and tries < 6000:
		tries += 1
		var z := rng.randf_range(-48.0, 8.0)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var x := river_cx(z) + side * rng.randf_range(river_w(z) + 2.5, 30.0)
		# Keep the left foreground open for the hero tree.
		if z > -4.0 and side < 0.0 and x > river_cx(z) - 9.0:
			continue
		if in_clearing(x, z, 2.0, true):
			continue
		per_variant[rng.randi() % names.size()].append(_random_xform(x, z, 0.85 * rng.randf_range(0.8, 1.25), 0.1))
		placed += 1
	for v in names.size():
		_multimesh(_vendor(names[v], 0.1), null, per_variant[v], not off.has("treeshadow"), 16.0)

	# A few big twisted trees deep in the forest for silhouette variety.
	for i in 6:
		var z := rng.randf_range(-48.0, -12.0)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var x := river_cx(z) + side * rng.randf_range(12.0, 28.0)
		if in_clearing(x, z, 4.0, true):
			continue
		_add_mesh(_vendor("TwistedTree_%d" % rng.randi_range(2, 5), 0.15), null, _random_xform(x, z, rng.randf_range(0.35, 0.45), 0.1))

	# Undergrowth along the banks and the forest floor.
	var kinds := [["Bush_Common", 0.7], ["Bush_Common_Flowers", 0.7], ["Fern_1", 0.28], ["Plant_1_Big", 0.3]]
	var sets: Array = []
	for k in kinds:
		sets.append([] as Array[Transform3D])
	for i in 170:
		var z := rng.randf_range(-40.0, 10.0)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var off := river_w(z) * rng.randf_range(1.15, 1.8) if i < 60 else rng.randf_range(river_w(z) + 2.0, 26.0)
		var x := river_cx(z) + side * off
		if in_clearing(x, z, 0.0, false):
			continue
		# Leave the near banks open so the stream reads from the camera.
		if z > 5.0 and off < river_w(z) * 2.0:
			continue
		var k := rng.randi() % kinds.size()
		sets[k].append(_random_xform(x, z, kinds[k][1] * rng.randf_range(0.75, 1.3), 0.05))
	# Undergrowth sits in the trees' shade anyway; its own shadows cost a lot of
	# alpha-tested shadow-pass fill for little visible gain.
	for k in kinds.size():
		_multimesh(_vendor(kinds[k][0], 0.06), null, sets[k], false, 12.0, 45.0)


func _add_props() -> void:
	var stone := _shader_mat("rock")
	stone.set_shader_parameter("stone", Color(0.72, 0.7, 0.64))
	stone.set_shader_parameter("moss_amount", 0.55)

	# Rope bridge (Sketchfab, CC-BY; see CREDITS.md). Its span runs along local -Z,
	# so turn it across the stream and hang it from the higher of the two banks.
	var bx := river_cx(BRIDGE_Z)
	var bank_y := maxf(_ground_y(bx - 5.0, BRIDGE_Z), _ground_y(bx + 5.0, BRIDGE_Z))
	var bb := Basis(Vector3.UP, PI / 2.0).scaled(Vector3(0.27, 0.22, 0.27))
	add_child(_instance("res://assets/bridge.glb", Transform3D(bb, Vector3(bx, bank_y + 0.05, BRIDGE_Z))))

	# Cottage (Sketchfab, CC-BY; see CREDITS.md), front porch facing the stream.
	var h := house_xz()
	var hb := Basis(Vector3.UP, deg_to_rad(HOUSE_YAW))
	var ht := Transform3D(hb.scaled(Vector3.ONE * HOUSE_SCALE), Vector3(h.x, _ground_y(h.x, h.y) - 0.05, h.y))
	add_child(_instance("res://assets/house.glb", ht))

	for v in VILLAGE:
		var vx: float = river_cx(v[2]) + v[1]
		var vb := Basis(Vector3.UP, deg_to_rad(v[3])).scaled(Vector3.ONE * VILLAGE_SCALE)
		var vt := Transform3D(vb, Vector3(vx, _ground_y(vx, v[2]) - 0.05, v[2]))
		add_child(_instance("res://assets/houses/%s.gltf" % v[0], vt))

	# Flat stepping-stone path from the bridge's right end to the front door.
	var rocks := _meshes("res://assets/rocks.glb")
	var from := Vector2(river_cx(BRIDGE_Z) + 5.0, BRIDGE_Z)
	var door := ht * Vector3(0.0, 0.0, 3.6)
	var to := Vector2(door.x, door.z)
	var steps := 7
	for i in steps:
		var p := from.lerp(to, float(i) / (steps - 1))
		p += Vector2(rng.randf_range(-0.2, 0.2), rng.randf_range(-0.15, 0.15))
		var s := rng.randf_range(0.3, 0.42)
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, 0.12, s * 0.85))
		_add_mesh(rocks["Rock%d" % (i % 6)], stone, Transform3D(b, Vector3(p.x, _ground_y(p.x, p.y) + 0.02, p.y)))


func _scatter_rocks() -> void:
	var m := _meshes("res://assets/rocks.glb")
	var mat := _shader_mat("rock")
	var meshes: Array = m.values()
	var pick := func() -> Mesh: return meshes[rng.randi() % meshes.size()]

	# Stepping stones breaking the surface.
	var z := 9.0
	while z > BRIDGE_Z + BRIDGE_CLEAR:
		for i in rng.randi_range(1, 3):
			var x := river_cx(z) + rng.randf_range(-0.8, 0.8) * river_w(z)
			var s := rng.randf_range(0.35, 0.95)
			var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, s * rng.randf_range(0.8, 1.2), s))
			_add_mesh(pick.call(), mat, Transform3D(b, Vector3(x, WATER_Y - 0.08 + rng.randf_range(-0.05, 0.12), z)))
		z -= rng.randf_range(1.4, 2.6)

	# Boulders along the banks.
	for i in 35:
		var bz := rng.randf_range(-30.0, 9.0)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var bx := river_cx(bz) + side * river_w(bz) * rng.randf_range(0.9, 1.6)
		var s := rng.randf_range(0.3, 1.1)
		if absf(bz - BRIDGE_Z) < BRIDGE_CLEAR + s:
			continue
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, s, s))
		_add_mesh(pick.call(), mat, Transform3D(b, Vector3(bx, _ground_y(bx, bz) - 0.1 * s, bz)))

	# Pebbles on the stream bed, seen through the water.
	var pebbles: Array[Transform3D] = []
	for i in 400:
		var pz := rng.randf_range(BRIDGE_Z - 4.0, 10.0)
		var px := river_cx(pz) + rng.randf_range(-0.9, 0.9) * river_w(pz)
		var s := rng.randf_range(0.08, 0.3)
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, s, s))
		pebbles.append(Transform3D(b, Vector3(px, _ground_y(px, pz), pz)))
	_multimesh(m["Rock0"], mat, pebbles, false)


func _scatter_grass() -> void:
	var names := ["Grass_Common_Short", "Grass_Common_Tall", "Grass_Wispy_Short", "Grass_Wispy_Tall"]
	var sets: Array = []
	for n in names:
		sets.append([] as Array[Transform3D])
	var placed := 0
	var tries := 0
	while placed < 16000 and tries < 40000:
		tries += 1
		# Denser near the camera, where single clumps are visible.
		var z := 12.0 - 54.0 * pow(rng.randf(), 1.5)
		var x := river_cx(z) + rng.randf_range(-26.0, 26.0)
		var y := _ground_y(x, z)
		if y < WATER_Y + 0.1 or on_plot(x, z, 0.2):
			continue
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3.ONE * rng.randf_range(0.28, 0.42))
		sets[rng.randi() % names.size()].append(Transform3D(b, Vector3(x, y - 0.03, z)))
		placed += 1
	for k in names.size():
		_multimesh(_vendor(names[k], 0.12, true), null, sets[k], false, 8.0, 30.0)

	# Wildflowers in loose patches.
	var flowers := ["Flower_3_Group", "Flower_4_Group", "Flower_3_Single", "Flower_4_Single", "Clover_1", "Clover_2"]
	var fsets: Array = []
	for n in flowers:
		fsets.append([] as Array[Transform3D])
	for p in 45:
		var cz := 11.0 - 45.0 * pow(rng.randf(), 1.3)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var cx := river_cx(cz) + side * rng.randf_range(river_w(cz) * 1.05, 20.0)
		var kind := rng.randi() % flowers.size()
		for j in 12:
			var x := cx + rng.randfn(0.0, 1.2)
			var z := cz + rng.randfn(0.0, 1.2)
			if _ground_y(x, z) < WATER_Y + 0.1 or in_clearing(x, z, -4.0, false):
				continue
			# Mostly one species per patch, with some mixing.
			var k := kind if rng.randf() < 0.75 else rng.randi() % flowers.size()
			fsets[k].append(_random_xform(x, z, rng.randf_range(0.18, 0.28), 0.02))
	for k in flowers.size():
		_multimesh(_vendor(flowers[k], 0.1, true), null, fsets[k], false, 8.0, 30.0)


func _scatter_pads() -> void:
	var pad := CylinderMesh.new()
	pad.top_radius = 0.22
	pad.bottom_radius = 0.2
	pad.height = 0.03
	pad.radial_segments = 20
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.4, 0.62, 0.22)
	mat.roughness = 0.5
	mat.rim_enabled = true
	var xforms: Array[Transform3D] = []
	for i in 24:
		var z := rng.randf_range(BRIDGE_Z + BRIDGE_CLEAR, 9.0)
		var side := -1.0 if rng.randf() < 0.5 else 1.0
		var x := river_cx(z) + side * river_w(z) * rng.randf_range(0.6, 0.95)
		var s := rng.randf_range(0.6, 1.6)
		var b := Basis(Vector3.UP, rng.randf() * TAU).scaled(Vector3(s, 1.0, s))
		xforms.append(Transform3D(b, Vector3(x, WATER_Y + 0.02, z)))
	_multimesh(pad, mat, xforms, false)


## Spawns the player on the right bank near the old overview camera, facing upstream.
func _add_player() -> void:
	player = CharacterBody3D.new()
	player.set_script(load("res://player.gd"))
	var z := 6.0
	var x := river_cx(z) + river_w(z) + 2.5
	player.position = Vector3(x, _ground_y(x, z) + 0.1, z)
	add_child(player)
	# Start with the camera behind the player, looking up the stream.
	player.model.rotation.y = PI
	player.pivot.global_position = player.global_position + Vector3.UP * 1.45
	if cam_mode == "portrait":
		player.pivot.rotation = Vector3(-0.15, PI, 0)
		player.arm.spring_length = 0.75


## Prints GPU-bound frame stats with vsync off:  godot --path . -- --bench
func _run_benchmark() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	if player:
		await _bench_directions()
		get_tree().quit()
		return
	for i in 120:
		await get_tree().process_frame
	var frames := 300
	var start := Time.get_ticks_usec()
	for i in frames:
		await get_tree().process_frame
	var ms := (Time.get_ticks_usec() - start) / 1000.0 / frames
	var draws := RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME)
	var prims := RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME)
	print("bench: %.2f ms/frame (%.0f fps), %d draw calls, %.2fM primitives" % [ms, 1000.0 / ms, draws, prims / 1e6])
	get_tree().quit()


## Turns the player camera through 8 headings and prints CPU/GPU frame time for each,
## since cost depends on what's in view.
func _bench_directions() -> void:
	var vp := get_viewport().get_viewport_rid()
	RenderingServer.viewport_set_measure_render_time(vp, true)
	print("bench off=%s" % [",".join(off)])
	var total := 0.0
	for i in 8:
		player.pivot.rotation.y = TAU * i / 8.0
		for f in 60:
			await get_tree().process_frame
		var frames := 120
		var gpu := 0.0
		var cpu := 0.0
		var start := Time.get_ticks_usec()
		for f in frames:
			await get_tree().process_frame
			gpu += RenderingServer.viewport_get_measured_render_time_gpu(vp)
			cpu += RenderingServer.viewport_get_measured_render_time_cpu(vp)
		var ms := (Time.get_ticks_usec() - start) / 1000.0 / frames
		total += ms
		var draws := RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME)
		var prims := RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME)
		print("  heading %3d: %6.2f ms frame | gpu %6.2f | render-cpu %5.2f | %5d draws | %.2fM prims" % [
			i * 45, ms, gpu / frames, cpu / frames, draws, prims / 1e6])
	print("  average: %.2f ms" % (total / 8.0))


func _take_screenshot() -> void:
	for i in shot_frames:
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	get_viewport().get_texture().get_image().save_png(shot_path)
	print("saved ", shot_path)
	get_tree().quit()
