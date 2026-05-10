extends VBoxContainer
class_name CueDisplay

## Reference to the CueManager to pull cue names from
@export var cue_manager: CueManager

## Accent color for the current cue
@export var current_color: Color = Color.WHITE

## Hint/faded color for prev/next cues
@export var hint_color: Color = Color.GRAY

## Color for the "current/next/previous cue" labels
@export var label_color: Color = Color(0.7, 0.7, 0.7)

## Font size for the current cue label
@export var current_font_size: int = 24

## Font size for the prev/next cue labels
@export var hint_font_size: int = 16

## Font size for the prefix labels
@export var prefix_font_size: int = 14

# Previous cue labels
var _prev_prefix_label: Label
var _prev_name_label: Label

# Current cue labels
var _current_prefix_label: Label
var _current_name_label: Label

# Next cue labels
var _next_prefix_label: Label
var _next_name_label: Label

func _ready() -> void:
    # Create HBoxContainers for each row with labels aligned vertically

    # Previous cue row
    var prev_row = HBoxContainer.new()
    prev_row.custom_minimum_size = Vector2(0, 20)
    add_child(prev_row)

    _prev_prefix_label = Label.new()
    _prev_prefix_label.text = "previous cue"
    _prev_prefix_label.add_theme_color_override("font_color", label_color)
    _prev_prefix_label.add_theme_font_size_override("font_size", prefix_font_size)
    _prev_prefix_label.custom_minimum_size = Vector2(120, 0)
    prev_row.add_child(_prev_prefix_label)

    _prev_name_label = Label.new()
    _prev_name_label.text = ""
    _prev_name_label.add_theme_color_override("font_color", hint_color)
    _prev_name_label.add_theme_font_size_override("font_size", hint_font_size)
    _prev_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    prev_row.add_child(_prev_name_label)

    # Current cue row
    var current_row = HBoxContainer.new()
    current_row.custom_minimum_size = Vector2(0, 30)
    add_child(current_row)

    _current_prefix_label = Label.new()
    _current_prefix_label.text = "current cue"
    _current_prefix_label.add_theme_color_override("font_color", label_color)
    _current_prefix_label.add_theme_font_size_override("font_size", prefix_font_size)
    _current_prefix_label.custom_minimum_size = Vector2(120, 0)
    current_row.add_child(_current_prefix_label)

    _current_name_label = Label.new()
    _current_name_label.text = ""
    _current_name_label.add_theme_color_override("font_color", current_color)
    _current_name_label.add_theme_font_size_override("font_size", current_font_size)
    _current_name_label.add_theme_font_override("font", ThemeDB.fallback_font.duplicate())
    # _current_name_label.get_theme_font("font").make_outline()
    _current_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    current_row.add_child(_current_name_label)

    # Next cue row
    var next_row = HBoxContainer.new()
    next_row.custom_minimum_size = Vector2(0, 20)
    add_child(next_row)

    _next_prefix_label = Label.new()
    _next_prefix_label.text = "next cue"
    _next_prefix_label.add_theme_color_override("font_color", label_color)
    _next_prefix_label.add_theme_font_size_override("font_size", prefix_font_size)
    _next_prefix_label.custom_minimum_size = Vector2(120, 0)
    next_row.add_child(_next_prefix_label)

    _next_name_label = Label.new()
    _next_name_label.text = ""
    _next_name_label.add_theme_color_override("font_color", hint_color)
    _next_name_label.add_theme_font_size_override("font_size", hint_font_size)
    _next_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
    next_row.add_child(_next_name_label)

    # Connect to cue changes
    if cue_manager:
        cue_manager.cue_changed.connect(_on_cue_changed)
        # Initial update
        _update_labels()

func _process(delta: float) -> void:
    # Continuously update labels to reflect current state
    _update_labels()

func _on_cue_changed(index: int, cue: Cue) -> void:
    _update_labels()

func _update_labels() -> void:
    if not cue_manager:
        _prev_name_label.text = ""
        _current_name_label.text = "(No CueManager)"
        _next_name_label.text = ""
        return

    var prev_name = cue_manager.get_previous_cue_name()
    var current_name = cue_manager.get_current_cue_name()
    var next_name = cue_manager.get_next_cue_name()

    _prev_name_label.text = prev_name if prev_name else ""
    _current_name_label.text = current_name if current_name else "(No Cue)"
    _next_name_label.text = next_name if next_name else ""
