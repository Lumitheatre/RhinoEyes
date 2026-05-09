@tool
extends Node
class_name Cue

## Transition duration in seconds when going to this cue. 0 = instant snap.
@export_range(0.0, 30.0, 0.05) var transition_time: float = 1.0

## One or more (entity_ids → state) pairs that make up this cue.
## Entities sharing an identical state can be listed together in one CueEntry.
@export var entries: Array[CueEntry] = []
