shader_type spatial;
// Ash-beige hair: darker roots fading to lighter tips along the clump UV.y,
// with faint strand bands across UV.x.

uniform vec3 root_color : source_color = vec3(0.47, 0.37, 0.27);
uniform vec3 mid_color : source_color = vec3(0.72, 0.62, 0.49);
uniform vec3 tip_color : source_color = vec3(0.80, 0.71, 0.58);

void fragment() {
	float v = UV.y;
	vec3 c = mix(root_color, mid_color, smoothstep(0.0, 0.35, v));
	c = mix(c, tip_color, smoothstep(0.35, 1.0, v));
	float strands = 0.94 + 0.06 * sin(UV.x * 6.2832 * 3.0 + v * 9.0);
	ALBEDO = c * strands;
	ROUGHNESS = 0.38;
	SPECULAR = 0.6;
}
