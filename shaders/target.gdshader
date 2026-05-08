shader_type spatial;
render_mode cull_disabled;

uniform vec3 tint_color : source_color = vec3(1.0);
uniform float brightness : hint_range(0.0, 10.0) = 1.0;

void fragment() {
	EMISSION = tint_color * brightness;;
}
