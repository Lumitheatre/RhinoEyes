@tool
extends Resource
class_name CueEntry

## The entity IDs this state applies to.
## Multiple IDs can share one EntityState for deduplication.
@export var entity_ids: Array[String] = []

## The state to apply to every entity listed in entity_ids.
@export var state: EntityState
