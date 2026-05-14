extends Node3D
class_name EyeTarget

## The target position in world space this node is seeking to reach
var destination_pos: Vector3

@export var lerp_speed: float = 5.0
@export var plane_offset: float = 0.0  # The height of the "stage" floor

## Movement sensitivity when using action inputs (joystick/analog)
## Multiplier for axis values (typically -1.0 to 1.0)
@export var action_move_sensitivity: float = 5.0

## Enable/disable boundary constraint
@export var constrain_to_window: bool = true

@export var y_limit = 5.0

func _ready() -> void:
    destination_pos = global_transform.origin

func _input(event: InputEvent) -> void:
    # Handle Mouse Click or Touchscreen Tap
    if event is InputEventMouseButton or event is InputEventScreenTouch:
        if event.pressed:
            update_destination(event.position)
            _clamp_to_window_bounds()

func _process(delta: float) -> void:
    # Continuously move towards the destination position for smooth movement
    var current_pos = global_transform.origin
    global_transform.origin = current_pos.lerp(destination_pos, lerp_speed * delta)

    # Handle action-based movement (right joystick analog)
    _handle_action_movement(delta)

func _handle_action_movement(delta: float) -> void:
    var move_offset = Vector3.ZERO

    # Get axis values for analog input (returns values from -1.0 to 1.0)
    var axis_x = Input.get_axis("target_move_x_minus", "target_move_x_plus")
    var axis_y = Input.get_axis("target_move_y_minus", "target_move_y_plus")

    # Apply sensitivity and delta time to the axis values
    move_offset.x = axis_x * action_move_sensitivity * delta
    move_offset.y = axis_y * action_move_sensitivity * delta

    # Apply the movement offset to the destination
    if move_offset != Vector3.ZERO:
        destination_pos += move_offset
        _clamp_to_window_bounds()

func _clamp_to_window_bounds() -> void:
    """Restrict the destination position to the window bounds in screen space."""
    if not constrain_to_window:
        return

    var cam = get_viewport().get_camera_3d()
    var viewport_size = get_viewport().get_visible_rect().size

    # Project destination to screen space to check bounds
    var screen_pos = cam.unproject_position(destination_pos)

    # Clamp horizontal bounds
    screen_pos.x = clamp(screen_pos.x, 0, viewport_size.x)

    # Clamp vertical bounds
    # If y_limit is set (>0), limit the top of the screen to y_limit height from bottom
    if y_limit > 0:
        # Get the bottom of the screen in world space
        var bottom_screen = Vector2(viewport_size.x / 2, viewport_size.y)
        var ray_origin_bottom = cam.project_ray_origin(bottom_screen)
        var ray_dir_bottom = cam.project_ray_normal(bottom_screen)
        var bottom_world_y = ray_origin_bottom.y
        if ray_dir_bottom.z != 0:
            var t_bottom = (plane_offset - ray_origin_bottom.z) / ray_dir_bottom.z
            bottom_world_y = (ray_origin_bottom + ray_dir_bottom * t_bottom).y

        # Calculate the maximum allowed world Y position
        var max_world_y = bottom_world_y + y_limit

        # Get the top limit in screen space
        var top_limit_screen_y = cam.unproject_position(Vector3(destination_pos.x, max_world_y, plane_offset)).y

        # Clamp screen Y to bottom of screen (viewport_size.y) and calculated top limit
        screen_pos.y = clamp(screen_pos.y, top_limit_screen_y, viewport_size.y)
    else:
        # No y_limit set, use full screen height
        screen_pos.y = clamp(screen_pos.y, 0, viewport_size.y)

    # Project back to world space
    var ray_origin = cam.project_ray_origin(screen_pos)
    var ray_dir = cam.project_ray_normal(screen_pos)

    # Intersect with the plane at plane_offset
    if ray_dir.z != 0:
        var t = (plane_offset - ray_origin.z) / ray_dir.z
        destination_pos = ray_origin + ray_dir * t

func update_destination(screen_pos: Vector2) -> void:
    var cam = get_viewport().get_camera_3d()
    var viewport_size = get_viewport().get_visible_rect().size

    # Clamp screen position to window bounds
    if constrain_to_window:
        screen_pos.x = clamp(screen_pos.x, 0, viewport_size.x)
        screen_pos.y = clamp(screen_pos.y, 0, viewport_size.y)

    var ray_origin = cam.project_ray_origin(screen_pos)
    var ray_dir = cam.project_ray_normal(screen_pos)

    # Project the click onto the XY plane (Z = offset)
    # Intersection of ray and plane: t = (plane_offset - origin.z) / dir.z
    if ray_dir.z != 0:
        var t = (plane_offset - ray_origin.z) / ray_dir.z
        destination_pos = ray_origin + ray_dir * t
