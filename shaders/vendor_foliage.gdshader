shader_type spatial;
render_mode cull_disabled;
// Alpha-tested foliage for the Quaternius MegaKit meshes, with wind.

uniform sampler2D albedo_tex : source_color, filter_linear_mipmap_anisotropic;
uniform vec4 tint : source_color = vec4(1.0);
uniform float sway = 0.08;
// Object-space height at which the sway reaches full strength.
uniform float sway_height = 1.0;
// Bend normals toward world up so grass shades as one soft field.
uniform bool up_normals = false;
uniform float backlight = 0.35;
// The tree leaf textures are flat-colour masks: keep their alpha, paint our own greens.
uniform bool recolor = false;
uniform vec3 dark : source_color = vec3(0.16, 0.36, 0.06);
uniform vec3 light : source_color = vec3(0.62, 0.82, 0.2);

varying vec3 wnorm;
varying vec3 inst;

void vertex() {
	vec3 w = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	float k = clamp(VERTEX.y / sway_height, 0.0, 1.0);
	k *= k;
	float t = TIME * 1.8 + dot(w, vec3(0.5, 0.2, 0.4));
	float gust = 0.6 + 0.4 * sin(TIME * 0.5 + w.x * 0.08 + w.z * 0.05);
	VERTEX.xz += vec2(sin(t), cos(t * 0.8)) * sway * k * gust;
	wnorm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	inst = MODEL_MATRIX[3].xyz;
	if (up_normals) {
		// Instances only spin about Y with uniform scale, so world up in object space
		// is just +Y; no per-vertex matrix inverse needed.
		NORMAL = normalize(mix(NORMAL, vec3(0.0, 1.0, 0.0), 0.8));
	}
}

void fragment() {
	vec4 c = texture(albedo_tex, UV) * tint;
	if (recolor) {
		float g = clamp(wnorm.y * 0.5 + 0.5, 0.0, 1.0);
		float v = fract(sin(dot(inst.xz, vec2(12.9898, 78.233))) * 43758.5453);
		vec3 lit = mix(light, vec3(0.78, 0.8, 0.28), v * 0.5);
		c.rgb = mix(dark, lit, smoothstep(0.15, 0.95, g)) * mix(0.85, 1.1, v);
	}
	ALBEDO = c.rgb;
	ALPHA = c.a;
	ALPHA_SCISSOR_THRESHOLD = 0.5;
	ALPHA_ANTIALIASING_EDGE = 0.3;
	ALPHA_TEXTURE_COORDINATE = UV * vec2(textureSize(albedo_tex, 0));
	BACKLIGHT = c.rgb * backlight;
	ROUGHNESS = 0.8;
	SPECULAR = 0.2;
}
