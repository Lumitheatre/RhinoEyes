@tool
extends MeshInstance3D
class_name EyeActor

@export var eye_shader: Shader = preload("res://shaders/eye_sprite.gdshader"):
	set(val):
		eye_shader = val
		_setup_material()

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
	else:
		push_error("EyeActor: Could not find EyeManager node. Make sure it's in the scene")
	
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
	
	if texture:
		material_override.set_shader_parameter("video_texture", texture)
	
	# Pass UV bounds directly to the shader
	material_override.set_shader_parameter("uv_offset", uv_offset)
	material_override.set_shader_parameter("uv_scale", uv_scale)

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
