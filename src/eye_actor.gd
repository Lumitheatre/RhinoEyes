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

@export_range(0.0, 1.0, 0.01) var opacity_multiplier: float = 1.0:
    set(val):
        opacity_multiplier = val
        _set_material_uniform("opacity_multiplier", opacity_multiplier)

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

@export_group("Cue System")

## Stable ID used by the cue system to address this actor.
## Gets set to the node name onready if empty
## Do not change this at runtime or cues will fail to find the actor!
@export var entity_id: String = ""

@export_group("Eye Character")

@export_storage var character_name: String = "":
    set(val):
        character_name = val
        _update_display()

@export_range(0.0, 360.0, 0.1) var view_angle: float = 0.0:
    set(val):
        view_angle = val
        _update_display()

@export_range(1, 3) var aggravation: int = 1:
    set(val):
        aggravation = val
        _update_display()

# References
var current_video_stream_player: VideoStreamPlayer

# Set to true by transition_to() to suppress auto-tracking during cue-driven angles.
var track_target: bool = true

var _cue_tween: Tween

func _ready():
    # Set up default plane mesh if none exists
    if not mesh:
        mesh = PlaneMesh.new()
        # Rotate 90 degrees on X axis to face the camera
        rotation.x = PI / 2.0

    _setup_material()
    _sync_all_proxy_properties()

    if entity_id == "":
        entity_id = name

    await _wait_for_eye_manager_ready()
    # print("Current character %s, angle %f, aggravation %d" % [character_name, view_angle, aggravation])
    _update_display()

func _get_property_list():
    var properties = []

    var eye_manager = _get_eye_manager()
    if eye_manager:
        var names = eye_manager.get_actor_names()
        if names and names.size() > 0:

            # Virtual helper selector populated by the manifest
            properties.append({
                "name": "_character_picker",
                "type": TYPE_STRING,
                "hint": PROPERTY_HINT_ENUM,
                "hint_string": ",".join(names),
                "usage": PROPERTY_USAGE_EDITOR
            })

    return properties

func _set(property, value):
    if property == "_character_picker":
        character_name = value
        return true
    return false

func _get(property):
    if property == "_character_picker":
        return character_name
    return null

func _setup_material():
    if not eye_shader:
        return

    # Create a unique material for this instance so actors can have different states
    var mat = ShaderMaterial.new()
    mat.shader = eye_shader
    material_override = mat

func _update_display():
    # print("Updating display for character '%s', angle %f, aggravation %d" % [character_name, view_angle, aggravation])

    if not is_inside_tree(): return
    _request_video_and_update()

## Request updated video texture and UV bounds from the EyeManager
func _request_video_and_update():
    if character_name == "":
        return

    var eye_manager = _get_eye_manager()
    if not eye_manager:
        return

    var result = eye_manager.get_video_texture_and_uvs(character_name, view_angle, aggravation)

    # print("Received video data for character '%s': %s" % [character_name, result])

    if result.is_empty():
        push_error("EyeActor: Failed to get video texture and UVs for character '%s'" % character_name)
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
        # print("Texture size: ", texture.get_width(), "x", texture.get_height())

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
    _set_material_uniform("opacity_multiplier", opacity_multiplier)
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

    # Update view angle to track the target
    _update_view_angle_to_target()

func _update_view_angle_to_target() -> void:
    """Poll the EyeManager for target position and update view_angle accordingly.
    Cardinal right (East) on the XY plane is 0 degrees.
    Skipped when track_target is false (e.g. during a cue transition).
    """
    if not track_target:
        return
    var eye_manager = _get_eye_manager()
    if not eye_manager:
        return

    var target_pos = eye_manager.get_target_position()
    var self_pos = global_position

    # Project both positions onto the XY plane (ignore Z)
    var self_xy = Vector2(self_pos.x, self_pos.y)
    var target_xy = Vector2(target_pos.x, target_pos.y)

    # Calculate direction vector from self to target
    var direction = (target_xy - self_xy).normalized()

    # Calculate angle: atan2 gives angle from positive X-axis (East = 0 degrees)
    # atan2(y, x) where y is up and x is right in 2D
    var angle_rad = atan2(direction.y, direction.x)
    var angle_deg = rad_to_deg(angle_rad)

    # Normalize to 0-360 range
    if angle_deg < 0:
        angle_deg += 360.0

    # Round to nearest integer for view_angle (assuming it expects discrete angles)
    view_angle = round(angle_deg)

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
func set_character_state(char_name: String, aggrav: int):
    character_name = char_name
    aggravation = aggrav
    _update_display()

## Public API for updating just angle (common operation)
func set_view_angle(angle: float):
    view_angle = angle
    _update_display()

## Public API for updating just aggravation
func set_aggravation(aggrav: int):
    aggravation = aggrav
    _update_display()

# --- CueEntity interface ---

## Returns the stable ID used to address this actor in cue entries.
func get_entity_id() -> String:
    if entity_id == "":
        push_error("EyeActor '%s': entity_id is empty" % name)
    return entity_id

## Captures the current cue-relevant state of this actor as an EyeActorState.
func capture_state() -> EyeActorState:
    var state := EyeActorState.new()
    state.aggravation = aggravation
    state.opacity_multiplier = opacity_multiplier
    state.track_target = track_target
    return state

## Applies an EntityState over [duration] seconds.
## - view_angle and opacity_multiplier are tweened.
## - aggravation is snapped immediately.
## - track_target is applied immediately, suppressing auto-tracking.
func transition_to(state: EntityState, duration: float) -> void:
    if not state is EyeActorState:
        push_error("EyeActor '%s': transition_to received unexpected state type." % name)
        return
    var eye_state := state as EyeActorState

    aggravation = eye_state.aggravation
    track_target = eye_state.track_target

    if _cue_tween:
        _cue_tween.kill()

    if duration <= 0.0:
        opacity_multiplier = eye_state.opacity_multiplier
        return

    _cue_tween = create_tween().set_parallel(true)
    _cue_tween.tween_property(self, "opacity_multiplier", eye_state.opacity_multiplier, duration)
