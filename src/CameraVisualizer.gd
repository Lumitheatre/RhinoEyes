extends Control
class_name CameraVisualizer

@export var schematic_camera: Camera3D
@export var clean_camera: Camera3D
@export var line_color: Color = Color.GREEN
@export var line_width: float = 2.0

func _process(_delta: float) -> void:
	# Trigger a redraw every frame to update the rectangle dynamically
	queue_redraw()

func _draw() -> void:
	if not schematic_camera or not clean_camera:
		return

	# 1. Get the 4 near-plane corners of the Clean Camera in 3D world space
	var corners: Array[Vector3] = _get_clean_camera_corners()

	# 2. Project those 3D points into the 2D screen space of the Schematic Camera
	var screen_points: Array[Vector2] = []
	for vertex in corners:
		# Check if the point is behind the schematic camera
		if schematic_camera.is_position_behind(vertex):
			return # Skip drawing if the clean camera is out of view

		var screen_pos = schematic_camera.unproject_position(vertex)
		screen_points.append(screen_pos)

	# 3. Draw lines connecting the 4 projected points to form a polygon
	if screen_points.size() == 4:
		draw_line(screen_points[0], screen_points[1], line_color, line_width)
		draw_line(screen_points[1], screen_points[2], line_color, line_width)
		draw_line(screen_points[2], screen_points[3], line_color, line_width)
		draw_line(screen_points[3], screen_points[0], line_color, line_width)

func _get_clean_camera_corners() -> Array[Vector3]:
	var cam_transform: Transform3D = clean_camera.global_transform
	var corners: Array[Vector3] = []

	if clean_camera.projection == Camera3D.PROJECTION_ORTHOGONAL:
		var size_y: float = clean_camera.size
		# Get aspect ratio from viewport target window
		var aspect: float = clean_camera.get_viewport().get_visible_rect().size.aspect()
		var size_x: float = size_y * aspect

		var h_x: float = size_x / 2.0
		var h_y: float = size_y / 2.0
		var z_offset: float = -clean_camera.near # Near plane offset

		# Define local 3D coordinates of the 4 corners
		corners.append(Vector3(-h_x,  h_y, z_offset)) # Top-Left
		corners.append(Vector3( h_x,  h_y, z_offset)) # Top-Right
		corners.append(Vector3( h_x, -h_y, z_offset)) # Bottom-Right
		corners.append(Vector3(-h_x, -h_y, z_offset)) # Bottom-Left

	else: # Fallback for perspective camera
		var fov: float = deg_to_rad(clean_camera.fov)
		var aspect: float = clean_camera.get_viewport().get_visible_rect().size.aspect()
		var near: float = clean_camera.near

		var h_y: float = tan(fov / 2.0) * near
		var h_x: float = h_y * aspect

		corners.append(Vector3(-h_x,  h_y, -near))
		corners.append(Vector3( h_x,  h_y, -near))
		corners.append(Vector3( h_x, -h_y, -near))
		corners.append(Vector3(-h_x, -h_y, -near))

	# Transform local camera points into global 3D world space
	for i in range(corners.size()):
		corners[i] = cam_transform * corners[i]

	return corners
