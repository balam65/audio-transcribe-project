(function () {
  function fitCanvas(canvas, container) {
    if (!canvas || !container) return null;

    const rect = container.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';

    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    return { ctx, width: rect.width, height: rect.height };
  }

  function createRain(width, height, count) {
    return Array.from({ length: count }, () => ({
      x: width * (0.04 + Math.random() * 0.78),
      y: Math.random() * height,
      len: 12 + Math.random() * 34,
      speed: 120 + Math.random() * 180,
      drift: (Math.random() - 0.5) * 12,
      alpha: 0.04 + Math.random() * 0.1,
      width: 0.4 + Math.random() * 0.8,
    }));
  }

  function createEmbers(width, height, count) {
    return Array.from({ length: count }, () => ({
      x: width * (0.04 + Math.random() * 0.56),
      y: height * (0.5 + Math.random() * 0.42),
      radius: 0.6 + Math.random() * 2.2,
      vx: -12 + Math.random() * 28,
      vy: -16 - Math.random() * 36,
      alpha: 0.16 + Math.random() * 0.36,
      glow: 5 + Math.random() * 12,
    }));
  }

  document.addEventListener('DOMContentLoaded', () => {
    const gate = document.getElementById('login-gate');
    const scene = gate?.querySelector('.gate__scene');
    const input = document.getElementById('secret-word');
    const toggle = document.getElementById('gate-visibility');
    const rainCanvas = document.getElementById('gate-fire-rain');
    const embersCanvas = document.getElementById('gate-embers');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    toggle?.addEventListener('click', () => {
      if (!input) return;

      const isPassword = input.type === 'password';
      input.type = isPassword ? 'text' : 'password';
      toggle.setAttribute('aria-pressed', String(isPassword));
      toggle.setAttribute('aria-label', isPassword ? 'Hide secret word' : 'Reveal secret word');
      input.focus();
    });

    if (!scene || !rainCanvas || !embersCanvas || reduceMotion) return;

    let rainState = fitCanvas(rainCanvas, scene);
    let emberState = fitCanvas(embersCanvas, scene);
    if (!rainState || !emberState) return;

    let rainDrops = createRain(rainState.width, rainState.height, Math.max(36, Math.round(rainState.width / 32)));
    let embers = createEmbers(emberState.width, emberState.height, Math.max(44, Math.round(emberState.width / 30)));
    let rafId = 0;
    let last = performance.now();

    function reset() {
      rainState = fitCanvas(rainCanvas, scene);
      emberState = fitCanvas(embersCanvas, scene);
      if (!rainState || !emberState) return;

      rainDrops = createRain(rainState.width, rainState.height, Math.max(36, Math.round(rainState.width / 32)));
      embers = createEmbers(emberState.width, emberState.height, Math.max(44, Math.round(emberState.width / 30)));
    }

    function drawRain(dt) {
      const { ctx, width, height } = rainState;
      ctx.clearRect(0, 0, width, height);

      for (const drop of rainDrops) {
        drop.y += drop.speed * dt;
        drop.x += drop.drift * dt;

        if (drop.y - drop.len > height) {
          drop.y = -drop.len - Math.random() * 80;
          drop.x = width * (0.04 + Math.random() * 0.78);
        }

        const gradient = ctx.createLinearGradient(drop.x, drop.y, drop.x - drop.drift * 0.18, drop.y - drop.len);
        gradient.addColorStop(0, `rgba(255, 208, 152, ${drop.alpha})`);
        gradient.addColorStop(0.45, `rgba(255, 107, 58, ${drop.alpha * 0.72})`);
        gradient.addColorStop(1, 'rgba(255, 24, 0, 0)');

        ctx.beginPath();
        ctx.lineWidth = drop.width;
        ctx.strokeStyle = gradient;
        ctx.moveTo(drop.x, drop.y);
        ctx.lineTo(drop.x - drop.drift * 0.18, drop.y - drop.len);
        ctx.stroke();
      }
    }

    function drawEmbers(dt) {
      const { ctx, width, height } = emberState;
      ctx.clearRect(0, 0, width, height);

      for (const ember of embers) {
        ember.x += ember.vx * dt;
        ember.y += ember.vy * dt;
        ember.alpha -= dt * 0.02;

        if (ember.alpha <= 0 || ember.y < -24 || ember.x < -24 || ember.x > width + 24) {
          ember.x = width * (0.04 + Math.random() * 0.56);
          ember.y = height * (0.5 + Math.random() * 0.42);
          ember.radius = 0.6 + Math.random() * 2.4;
          ember.vx = -12 + Math.random() * 30;
          ember.vy = -18 - Math.random() * 42;
          ember.alpha = 0.16 + Math.random() * 0.36;
          ember.glow = 5 + Math.random() * 12;
        }

        ctx.beginPath();
        ctx.fillStyle = `rgba(255, 124, 74, ${ember.alpha})`;
        ctx.shadowColor = `rgba(255, 86, 34, ${Math.min(ember.alpha, 0.44)})`;
        ctx.shadowBlur = ember.glow;
        ctx.arc(ember.x, ember.y, ember.radius, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.shadowBlur = 0;
    }

    function frame(now) {
      const dt = Math.min((now - last) / 1000, 0.033);
      last = now;
      drawRain(dt);
      drawEmbers(dt);
      rafId = window.requestAnimationFrame(frame);
    }

    const resizeObserver = new ResizeObserver(reset);
    resizeObserver.observe(scene);
    window.addEventListener('resize', reset);

    rafId = window.requestAnimationFrame(frame);

    document.addEventListener('visibilitychange', () => {
      if (document.hidden && rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
        return;
      }

      if (!document.hidden && !rafId) {
        last = performance.now();
        rafId = window.requestAnimationFrame(frame);
      }
    });
  });
})();
