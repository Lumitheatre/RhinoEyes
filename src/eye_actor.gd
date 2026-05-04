@tool
extends MeshInstance3D
class_name EyeActor

@export var eye_shader: Shader = preload("res://shaders/eye_sprite.gdshader"):
	set(val):
		eye_shader = val
		_setup_material()

# --- Proxy Properties for Shader Uniforms ---
@export_group("Film Aesthetics")

@export_range(0.0, 5.0, 0.01) var exposure: float = 1.2:
	set(val):
		exposure = val
		_set_material_uniform("exposure", exposure)

@export_range(0.0, 5.0, 0.01) var contrast: float = 3.0:
	set(val):
		contrast = val
		_set_material_uniform("contrast", contrast)

@export_range(0.0, 10.0, 0.01) var emission_strength: float = 1.2:
	set(val):
		emission_strength = val
		_set_material_uniform("emission_strength", emission_strength)

@export_group("Film Flicker")

@export var enable_flicker: bool = true:
	set(val):
		enable_flicker = val
		_set_material_uniform("enable_flicker", enable_flicker)

@export_range(1.0, 30.0, 0.1) var flicker_frequency: float = 15.0:
	set(val):
		flicker_frequency = val
		_set_material_uniform("flicker_frequency", flicker_frequency)

@export_range(0.0, 1.0, 0.01) var flicker_amplitude: float = 0.08:
	set(val):
		flicker_amplitude = val
		_set_material_uniform("flicker_amplitude", flicker_amplitude)

@export_range(0.0, 100000.0, 1.0) var flicker_seed: float = 43758.5453:
	set(val):
		flicker_seed = val
		_set_material_uniform("flicker_seed", flicker_seed)

@export_group("Eye Character")

# State - the only things the actor tracks
var _character_name: String = ""
var _view_angle: int = 0
var _aggravation: int = 1

# References
var current_video_stream_player: VideoStreamPlayer

func _ready():
	# Set up default plane mesh if none exists
	if not mesh:
		mesh = PlaneMesh.new()
		# Rotate 90 degrees on X axis to face the camera
		rotation.x = PI / 2.0

	_setup_material()
	_sync_all_proxy_properties()
	await _wait_for_eye_manager_ready()
	_update_display()

func _get_property_list():
	var properties = []

	# Get character list from EyeManager
	var eye_manager = _get_eye_manager()
	if eye_manager:
		var names = eye_manager.get_actor_names()
		if names and names.size() > 0:
			properties.append({
				"name": "character_name",
				"type": TYPE_STRING,
				"hint": PROPERTY_HINT_ENUM,
				"hint_string": ",".join(names)
			})

	if _character_name != "":
		properties.append({
			"name": "view_angle",
			"type": TYPE_FLOAT,
			"hint": PROPERTY_HINT_RANGE,
			"hint_string": "0,360,0.1", # Min, Max, Step
			"usage": PROPERTY_USAGE_DEFAULT # Makes it appear in Inspector and save
		})
		properties.append({
			"name": "aggravation",
			"type": TYPE_INT,
			"hint": PROPERTY_HINT_RANGE,
			"hint_string": "1,3"
		})

	return properties

func _get(property):
	if property == "character_name":
		return _character_name
	if property == "view_angle":
		return _view_angle
	if property == "aggravation":
		return _aggravation
	return null

func _set(property, value):
	if property == "character_name":
		_character_name = value
		_update_display()
		return true
	if property == "view_angle":
		_view_angle = value
		_update_display()
		return true
	if property == "aggravation":
		_aggravation = value
		_update_display()
		return true
	return false

func _setup_material():
	if not eye_shader:
		return

	# Create a unique material for this instance so actors can have different states
	var mat = ShaderMaterial.new()
	mat.shader = eye_shader
	material_override = mat

func _update_display():
	if not is_inside_tree(): return
	_request_video_and_update()

## Request updated video texture and UV bounds from the EyeManager
func _request_video_and_update():
	if _character_name == "":
		return

	var eye_manager = _get_eye_manager()
	if not eye_manager:
		push_error("EyeActor: Could not find EyeManager node. Make sure it's in the scene with unique name '%EyeManager'")
		return

	var result = eye_manager.get_video_texture_and_uvs(_character_name, _view_angle, _aggravation)

	# print("Received video data for character '%s': %s" % [_character_name, result])

	if result.is_empty():
		push_error("EyeActor: Failed to get video texture and UVs for character '%s'" % _character_name)
		return

	# Release old video reference if we're switching
	if current_video_stream_player and current_video_stream_player != result.get("video_stream_player"):
		eye_manager.release_video_player(current_video_stream_player)

	current_video_stream_player = result.get("video_stream_player")

	if material_override:
		_apply_texture_and_uvs(result)

## Apply texture and UV information from the manager to the shader
func _apply_texture_and_uvs(texture_data: Dictionary):
	if not material_override:
		return

	var texture = texture_data.get("texture")
	var uv_offset = texture_data.get("uv_offset", Vector2.ZERO)
	var uv_scale = texture_data.get("uv_scale", Vector2.ONE)
	var aspect_ratio = texture_data.get("aspect_ratio", 1.0)

	if texture:
		material_override.set_shader_parameter("video_texture", texture)

	# Pass UV bounds and aspect ratio to the shader
	material_override.set_shader_parameter("uv_offset", uv_offset)
	material_override.set_shader_parameter("uv_scale", uv_scale)
	material_override.set_shader_parameter("tile_aspect_ratio", aspect_ratio)

## Sync all proxy properties to the shader material
func _sync_all_proxy_properties():
	# Call this in _ready to ensure the saved values are loaded
	# into the unique material instance.
	_set_material_uniform("exposure", exposure)
	_set_material_uniform("contrast", contrast)
	_set_material_uniform("emission_strength", emission_strength)
	_set_material_uniform("enable_flicker", enable_flicker)
	_set_material_uniform("flicker_frequency", flicker_frequency)
	_set_material_uniform("flicker_amplitude", flicker_amplitude)
	_set_material_uniform("flicker_seed", flicker_seed)

## Robust helper function for setting shader uniforms
func _set_material_uniform(uniform_name: String, value):
	# Using material_override ensures we are touching the unique instance
	if material_override and material_override is ShaderMaterial:
		material_override.set_shader_parameter(uniform_name, value)

func _process(_delta):
	# Update the texture every frame so it plays in the editor viewport
	if current_video_stream_player and material_override:
		var tex = current_video_stream_player.get_video_texture()
		if tex:
			material_override.set_shader_parameter("video_texture", tex)

func _exit_tree():
	if current_video_stream_player:
		var eye_manager = _get_eye_manager()
		if eye_manager:
			eye_manager.release_video_player(current_video_stream_player)
		current_video_stream_player = null

## Get the EyeManager node by unique name (%EyeManager)
func _get_eye_manager() -> EyeManager:
	if not is_inside_tree():
		return null
	return EyeManager.instance

func _wait_for_eye_manager_ready():
	var eye_manager = _get_eye_manager()
	if eye_manager:
		await eye_manager.ready

## Public API for setting character state (useful for runtime)
func set_character_state(name: String, angle: int, aggrav: int):
	_character_name = name
	_view_angle = angle
	_aggravation = aggrav
	_update_display()

## Public API for updating just angle (common operation)
func set_view_angle(angle: int):
	_view_angle = angle
	_update_display()

## Public API for updating just aggravation
func set_aggravation(aggrav: int):
	_aggravation = aggrav
	_update_display()
