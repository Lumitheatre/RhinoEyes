## CueEntity — duck-typed interface for nodes that participate in the cue system.
##
## Any Node implementing the three methods below is treated as a CueEntity by CueManager.
## GDScript does not support multiple inheritance, so this class serves as documentation only.
##
## Required methods:
##
##   func get_entity_id() -> String
##       Returns a stable, unique string that identifies this entity in cue entries.
##
##   func capture_cue_state() -> EntityState
##       Returns an EntityState snapshot of the entity's current cue-relevant parameters.
##       Used by the editor helper to record live state into a new Cue.
##
##   func transition_to(state: EntityState, duration: float) -> void
##       Applies the given EntityState. duration == 0 means instant (snap).
##       Each entity is responsible for deciding how to interpolate its own parameters.
class_name CueEntity
extends RefCounted
