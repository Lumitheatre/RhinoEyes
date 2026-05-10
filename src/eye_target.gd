extends Node3D
class_name EyeTarget

## The target position in world space this node is seeking to reach
var destination_pos: Vector3

@export var lerp_speed: float = 5.0
@export var plane_offset: float = 0.0  # The height of the "stage" floor

## Movement speed when using action inputs (in units per second)
@export var action_move_speed: float = 5.0

var _target_tween: Tween

func _ready() -> void:
    destination_pos = global_transform.origin

func _input(event: InputEvent) -> void:
    # Handle Mouse Click or Touchscreen Tap
    if event is InputEventMouseButton or event is InputEventScreenTouch:
        if event.pressed:
            update_destination(event.position)

func _process(delta: float) -> void:
    # Continuously move towards the destination position for smooth movement
    var current_pos = global_transform.origin
    global_transform.origin = current_pos.lerp(destination_pos, lerp_speed * delta)

    # Handle action-based movement (right joystick analog)
    _handle_action_movement(delta)

func _handle_action_movement(delta: float) -> void:
    var move_offset = Vector3.ZERO

    if Input.is_action_pressed("target_move_x_plus"):
        move_offset.x += action_move_speed * delta
    if Input.is_action_pressed("target_move_x_minus"):
        move_offset.x -= action_move_speed * delta
    if Input.is_action_pressed("target_move_y_plus"):
        move_offset.y += action_move_speed * delta
    if Input.is_action_pressed("target_move_y_minus"):
        move_offset.y -= action_move_speed * delta

    # Apply the movement offset to the destination
    if move_offset != Vector3.ZERO:
        destination_pos += move_offset

func update_destination(screen_pos: Vector2) -> void:
    var cam = get_viewport().get_camera_3d()
    var ray_origin = cam.project_ray_origin(screen_pos)
    var ray_dir = cam.project_ray_normal(screen_pos)

    # Project the click onto the XY plane (Z = offset)
    # Intersection of ray and plane: t = (plane_offset - origin.z) / dir.z
    if ray_dir.z != 0:
        var t = (plane_offset - ray_origin.z) / ray_dir.z
        destination_pos = ray_origin + ray_dir * t
