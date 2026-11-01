shader_type spatial;
render_mode cull_disabled;

uniform sampler2D screen_tex : hint_screen_texture, filter_linear_mipmap;
uniform sampler2D depth_tex : hint_depth_texture, filter_linear_mipmap;
uniform sampler2D normal_a : hint_normal, repeat_enable;
uniform sampler2D normal_b : hint_normal, repeat_enable;
uniform sampler2D foam_noise : repeat_enable;

uniform vec3 shallow_col : source_color = vec3(0.55, 1.0, 0.88);
uniform vec3 deep_col : source_color = vec3(0.08, 0.58, 0.6);
uniform float depth_scale = 1.4;
uniform float refraction = 0.04;
uniform vec2 flow = vec2(0.0, 0.18);

varying vec3 wpos;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

float view_depth(vec2 uv, mat4 inv_proj) {
	float raw = textureLod(depth_tex, uv, 0.0).r;
	vec4 vp = inv_proj * vec4(uv * 2.0 - 1.0, raw, 1.0);
	return vp.z / vp.w;
}

void fragment() {
	vec2 uv = wpos.xz;
	vec3 na = texture(normal_a, uv * 0.18 + flow * TIME).rgb;
	vec3 nb = texture(normal_b, uv * 0.31 + flow * TIME * 1.6 + vec2(0.07, 0.0) * TIME).rgb;
	vec3 nmap = normalize(na + nb - 1.0);
	NORMAL_MAP = nmap;
	NORMAL_MAP_DEPTH = 0.5;

	float depth = max(VERTEX.z - view_depth(SCREEN_UV, INV_PROJECTION_MATRIX), 0.0);
	vec2 ruv = SCREEN_UV + (nmap.xy * 2.0 - 1.0) * refraction * clamp(depth, 0.0, 1.0);
	float rz = view_depth(ruv, INV_PROJECTION_MATRIX);
	// Don't refract things that sit in front of the water surface.
	if (rz > VERTEX.z) {
		ruv = SCREEN_UV;
	} else {
		depth = VERTEX.z - rz;
	}
	vec3 refr = textureLod(screen_tex, ruv, 0.0).rgb;

	float murk = clamp(1.0 - exp(-depth * depth_scale), 0.0, 1.0);
	vec3 water = mix(shallow_col, deep_col, murk);
	float body = clamp(murk * 0.6 + 0.08, 0.0, 1.0);

	float fn = texture(foam_noise, uv * 0.7 + flow * TIME * 2.0).r;
	float foam = smoothstep(0.14, 0.02, depth - fn * 0.12);

	ALBEDO = mix(water * body, vec3(0.95), foam * 0.85);
	EMISSION = refr * mix(shallow_col, vec3(1.0), 0.35) * (1.0 - body) * (1.0 - foam);
	ROUGHNESS = mix(0.04, 0.6, foam);
	SPECULAR = 0.6;
}
