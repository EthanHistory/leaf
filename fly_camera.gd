extends Camera3D
## Hold right mouse to look around, WASD to move, Q/E down/up, Shift to go faster.

const SPEED := 6.0
const SENSITIVITY := 0.003


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_RIGHT:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if event.pressed else Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotation.y -= event.relative.x * SENSITIVITY
		rotation.x = clamp(rotation.x - event.relative.y * SENSITIVITY, -1.5, 1.5)


func _process(delta: float) -> void:
	var dir := Vector3.ZERO
	if Input.is_key_pressed(KEY_W): dir -= basis.z
	if Input.is_key_pressed(KEY_S): dir += basis.z
	if Input.is_key_pressed(KEY_A): dir -= basis.x
	if Input.is_key_pressed(KEY_D): dir += basis.x
	if Input.is_key_pressed(KEY_E): dir += Vector3.UP
	if Input.is_key_pressed(KEY_Q): dir -= Vector3.UP
	var speed := SPEED * (3.0 if Input.is_key_pressed(KEY_SHIFT) else 1.0)
	position += dir.normalized() * speed * delta
