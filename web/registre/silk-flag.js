// <silk-flag> — WebGL silk/fabric shader rendered as a French tricolour (blue | white | red, left→right).
// Port of the "Silk" R3F shader to plain WebGL, no dependencies. Attributes: speed, scale, noise, rotation.
(function () {
  const VERT = `attribute vec2 aPos; varying vec2 vUv; void main(){ vUv = aPos*0.5+0.5; gl_Position = vec4(aPos,0.0,1.0); }`;
  const FRAG = `precision highp float;
varying vec2 vUv;
uniform float uTime, uSpeed, uScale, uRotation, uNoise, uAspect;
uniform vec3 uBlue, uWhite, uRed;
const float e = 2.71828182845904523536;
float noise(vec2 p){ vec2 r = (e * sin(e * p)); return fract(r.x * r.y * (1.0 + p.x)); }
vec2 rot(vec2 uv, float a){ float c=cos(a), s=sin(a); return mat2(c,-s,s,c)*uv; }
void main(){
  float rnd = noise(gl_FragCoord.xy);
  vec2 uv = rot(vec2(vUv.x*uAspect, vUv.y) * uScale, uRotation);
  vec2 tex = uv * uScale;
  float t = uSpeed * uTime;
  tex.y += 0.03 * sin(8.0 * tex.x - t);
  float pattern = 0.6 + 0.4 * sin(5.0 * (tex.x + tex.y + cos(3.0 * tex.x + 5.0 * tex.y) + 0.02 * t) + sin(20.0 * (tex.x + tex.y - 0.1 * t)));
  // fabric displacement of the band boundaries so the stripes ripple with the folds
  float wob = 0.012 * sin(6.0 * vUv.y + 0.6 * t) + 0.01 * (pattern - 0.6);
  float x = vUv.x + wob;
  float b1 = smoothstep(0.3333 - 0.004, 0.3333 + 0.004, x);
  float b2 = smoothstep(0.6667 - 0.004, 0.6667 + 0.004, x);
  vec3 base = mix(uBlue, uWhite, b1);
  base = mix(base, uRed, b2);
  float fold = smoothstep(0.28, 0.9, pattern);
  float spec = smoothstep(0.72, 0.98, pattern);
  vec3 shadowC = base * 0.62;
  vec3 bodyC = min(base * 1.12, vec3(1.0));
  vec3 lit = mix(shadowC, bodyC, fold);
  lit = mix(lit, vec3(1.0), spec * 0.55);
  float fine = noise(gl_FragCoord.xy * 0.63 + vec2(17.0, 41.0));
  float grain = (rnd + fine - 1.0) * clamp(uNoise * 0.038, 0.0, 0.16);
  gl_FragColor = vec4(clamp(lit + grain, 0.0, 1.0), 1.0);
}`;
  const hex = h => { h = h.replace('#', ''); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255); };
  class SilkFlag extends HTMLElement {
    connectedCallback() {
      this.style.cssText += ';display:block;width:100%;height:100%;min-height:1px';
      if (!this.canvas) { this.canvas = document.createElement('canvas'); this.canvas.style.cssText = 'width:100%;height:100%;display:block'; this.appendChild(this.canvas); }
      const gl = this.gl = this.canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'high-performance' });
      if (!gl) { this.style.background = 'linear-gradient(90deg,#0A2A8F 0 33.3%,#F2F0EA 33.3% 66.6%,#C4101C 66.6%)'; return; }
      const mk = (t, s) => { const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh); return sh; };
      const prog = gl.createProgram(); gl.attachShader(prog, mk(gl.VERTEX_SHADER, VERT)); gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FRAG)); gl.linkProgram(prog); gl.useProgram(prog);
      const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, 'aPos'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      this.u = {}; ['uTime', 'uSpeed', 'uScale', 'uRotation', 'uNoise', 'uAspect', 'uBlue', 'uWhite', 'uRed'].forEach(n => this.u[n] = gl.getUniformLocation(prog, n));
      gl.uniform3fv(this.u.uBlue, hex(this.getAttribute('blue') || '#0A2A8F'));
      gl.uniform3fv(this.u.uWhite, hex(this.getAttribute('white') || '#F2F0EA'));
      gl.uniform3fv(this.u.uRed, hex(this.getAttribute('red') || '#C4101C'));
      this.t = 0; this.last = performance.now(); this.visible = true;
      this.reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(this);
      this.io = new IntersectionObserver(en => { this.visible = en[0].isIntersecting; if (this.visible) this.loop(); }); this.io.observe(this);
      this.resize(); this.loop();
      requestAnimationFrame(() => this.resize());
      setTimeout(() => this.resize(), 300);
    }
    disconnectedCallback() { cancelAnimationFrame(this.raf); this.ro && this.ro.disconnect(); this.io && this.io.disconnect(); }
    needsResize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      return this.canvas.width !== Math.round(Math.max(1, this.clientWidth) * dpr) || this.canvas.height !== Math.round(Math.max(1, this.clientHeight) * dpr);
    }
    resize() {
      if (!this.gl) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1); const w = Math.max(1, this.clientWidth), h = Math.max(1, this.clientHeight);
      this.canvas.width = Math.round(w * dpr); this.canvas.height = Math.round(h * dpr); this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      this.gl.uniform1f(this.u.uAspect, w / h); this.draw(true);
    }
    draw(fromResize) {
      if (!fromResize && this.needsResize()) { this.resize(); return; }
      const gl = this.gl, f = n => parseFloat(this.getAttribute(n));
      gl.uniform1f(this.u.uTime, this.t);
      gl.uniform1f(this.u.uSpeed, isNaN(f('speed')) ? 5 : f('speed'));
      gl.uniform1f(this.u.uScale, isNaN(f('scale')) ? 1 : f('scale'));
      gl.uniform1f(this.u.uRotation, isNaN(f('rotation')) ? 0 : f('rotation'));
      gl.uniform1f(this.u.uNoise, isNaN(f('noise')) ? 1.5 : f('noise'));
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    loop() {
      cancelAnimationFrame(this.raf);
      if (this.reduced || this.getAttribute('paused') === 'true') { this.t = 3; this.draw(); return; }
      const step = now => { const d = (now - this.last) / 1000; this.last = now; this.t += 0.1 * d; this.draw(); if (this.visible) this.raf = requestAnimationFrame(step); };
      this.raf = requestAnimationFrame(step);
    }
    static get observedAttributes() { return ['paused']; }
    attributeChangedCallback() { if (this.gl) this.loop(); }
  }
  if (!customElements.get('silk-flag')) customElements.define('silk-flag', SilkFlag);
})();
