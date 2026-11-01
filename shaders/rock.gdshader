shader_type spatial;

uniform sampler2D noise_tex : repeat_enable;
uniform vec3 stone : source_color = vec3(0.92, 0.9, 0.84);
uniform vec3 stone_dark : source_color = vec3(0.7, 0.7, 0.68);
uniform vec3 moss : source_color = vec3(0.36, 0.52, 0.12);
uniform float moss_amount = 0.5;
uniform float water_y = -0.2;

varying vec3 wpos;
varying vec3 wnorm;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	wnorm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

float tri(vec3 p, vec3 n) {
	vec3 w = abs(n);
	w /= (w.x + w.y + w.z);
	return texture(noise_tex, p.yz).r * w.x + texture(noise_tex, p.xz).r * w.y + texture(noise_tex, p.xy).r * w.z;
}

void fragment() {
	float n = tri(wpos * 0.6, wnorm);
	float speck = tri(wpos * 3.0, wnorm);
	vec3 c = mix(stone_dark, stone, smoothstep(0.25, 0.75, n)) * (0.9 + 0.2 * speck);
	float m = smoothstep(0.55, 0.9, wnorm.y + (n - 0.5) * 0.8) * smoothstep(water_y + 0.05, water_y + 0.35, wpos.y);
	c = mix(c, moss * (0.8 + 0.4 * speck), m * moss_amount);
	float wet = 1.0 - smoothstep(water_y, water_y + 0.08, wpos.y);
	ALBEDO = c * (1.0 - wet * 0.35);
	ROUGHNESS = mix(0.85, 0.25, wet);
}
