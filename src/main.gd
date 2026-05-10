extends Node3D

@onready var main_viewport = get_viewport()
@onready var sub_window = $SecondaryWindow

func _ready():
    # Tell the sub-window to look at the same 3D world as the main game
    sub_window.world_3d = main_viewport.world_3d

    # Optional: Ensure the window is visible
    sub_window.show()
