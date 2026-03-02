const state = {
  projects: [],
  currentProject: null,
  mode: 'none',
  draftPoints: [],
  calibrationPoints: [],
  image: null,
};

const el = {
  projectName: document.getElementById('projectName'),
  projectDescription: document.getElementById('projectDescription'),
  createProjectBtn: document.getElementById('createProjectBtn'),
  projectSelect: document.getElementById('projectSelect'),
  loadProjectBtn: document.getElementById('loadProjectBtn'),
  planFile: document.getElementById('planFile'),
  uploadPlanBtn: document.getElementById('uploadPlanBtn'),
  modeInfo: document.getElementById('modeInfo'),
  finishPolygonBtn: document.getElementById('finishPolygonBtn'),
  entityName: document.getElementById('entityName'),
  zoneColor: document.getElementById('zoneColor'),
  distanceMeters: document.getElementById('distanceMeters'),
  gridStep: document.getElementById('gridStep'),
  trackFile: document.getElementById('trackFile'),
  trackVolume: document.getElementById('trackVolume'),
  trackAutostart: document.getElementById('trackAutostart'),
  trackLooped: document.getElementById('trackLooped'),
  exportBtn: document.getElementById('exportBtn'),
  log: document.getElementById('log'),
  canvas: document.getElementById('canvas'),
};
const ctx = el.canvas.getContext('2d');

function log(message) {
  el.log.textContent = `${new Date().toLocaleTimeString()} ${message}\n${el.log.textContent}`;
}

async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Ошибка ${res.status}`);
  }
  return res;
}

async function loadProjects() {
  const res = await api('/api/projects');
  state.projects = await res.json();
  el.projectSelect.innerHTML = '<option value="">Выберите проект</option>';
  state.projects.forEach((p) => {
    const option = document.createElement('option');
    option.value = p.id;
    option.textContent = `${p.id}: ${p.name}`;
    el.projectSelect.appendChild(option);
  });
}

async function loadProjectById(id) {
  const res = await api(`/api/projects/${id}`);
  state.currentProject = await res.json();
  state.draftPoints = [];
  state.calibrationPoints = [];
  if (state.currentProject.floorPlanPath) {
    const img = new Image();
    img.src = state.currentProject.floorPlanPath;
    await img.decode();
    state.image = img;
  } else {
    state.image = null;
  }
  draw();
  log(`Проект «${state.currentProject.name}» открыт`);
}

function setMode(mode) {
  state.mode = mode;
  state.draftPoints = [];
  state.calibrationPoints = [];
  el.modeInfo.textContent = `Текущий режим: ${mode}`;
  draw();
}

function getCanvasPoint(event) {
  const rect = el.canvas.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  };
}

function drawPolygon(points, stroke, fill = null) {
  if (!points.length) return;
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  points.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.closePath();
  ctx.lineWidth = 2;
  ctx.strokeStyle = stroke;
  ctx.stroke();
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
}

function drawGrid() {
  if (!state.currentProject?.scale || !state.currentProject?.gridStep) return;
  const step = state.currentProject.scale * state.currentProject.gridStep;
  if (step < 10) return;
  ctx.save();
  ctx.strokeStyle = 'rgba(80,80,80,0.2)';
  ctx.lineWidth = 1;
  for (let x = 0; x < el.canvas.width; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, el.canvas.height);
    ctx.stroke();
  }
  for (let y = 0; y < el.canvas.height; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(el.canvas.width, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawTracks() {
  (state.currentProject?.tracks || []).forEach((t) => {
    ctx.beginPath();
    ctx.arc(t.x, t.y, 8, 0, Math.PI * 2);
    ctx.fillStyle = '#f97316';
    ctx.fill();
    ctx.strokeStyle = '#7c2d12';
    ctx.stroke();
    ctx.fillStyle = '#111';
    ctx.fillText(t.name, t.x + 10, t.y - 10);
  });
}

function draw() {
  ctx.clearRect(0, 0, el.canvas.width, el.canvas.height);
  if (state.image) {
    ctx.drawImage(state.image, 0, 0, el.canvas.width, el.canvas.height);
  }

  drawGrid();

  (state.currentProject?.rooms || []).forEach((r) => drawPolygon(r.points, '#2563eb', 'rgba(37,99,235,0.15)'));
  (state.currentProject?.zones || []).forEach((z) => drawPolygon(z.points, z.color, `${z.color}55`));
  drawTracks();

  if (state.draftPoints.length > 1) {
    ctx.beginPath();
    ctx.moveTo(state.draftPoints[0].x, state.draftPoints[0].y);
    state.draftPoints.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
    ctx.strokeStyle = '#dc2626';
    ctx.stroke();
  }
  state.draftPoints.forEach((p) => {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#dc2626';
    ctx.fill();
  });
}

async function savePolygon() {
  if (!state.currentProject) return;
  if (state.draftPoints.length < 3) {
    log('Недостаточно точек для полигона');
    return;
  }
  const name = el.entityName.value.trim();
  if (!name) {
    log('Введите название объекта');
    return;
  }

  if (state.mode === 'room') {
    await api(`/api/projects/${state.currentProject.id}/rooms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, points: state.draftPoints }),
    });
    log(`Зал «${name}» добавлен`);
  }

  if (state.mode === 'zone') {
    await api(`/api/projects/${state.currentProject.id}/zones`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, points: state.draftPoints, color: el.zoneColor.value }),
    });
    log(`Зона «${name}» добавлена`);
  }

  await loadProjectById(state.currentProject.id);
}

el.canvas.addEventListener('click', async (event) => {
  if (!state.currentProject) return;
  const point = getCanvasPoint(event);

  if (state.mode === 'room' || state.mode === 'zone') {
    state.draftPoints.push(point);
    draw();
    return;
  }

  if (state.mode === 'calibration') {
    state.calibrationPoints.push(point);
    if (state.calibrationPoints.length === 2) {
      await api(`/api/projects/${state.currentProject.id}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          points: state.calibrationPoints,
          distanceMeters: Number(el.distanceMeters.value),
          gridStep: Number(el.gridStep.value),
        }),
      });
      log('Калибровка сохранена');
      await loadProjectById(state.currentProject.id);
    }
    draw();
    return;
  }

  if (state.mode === 'track') {
    const name = el.entityName.value.trim();
    const file = el.trackFile.files[0];
    if (!name || !file) {
      log('Для трека нужны название и MP3 файл');
      return;
    }
    const form = new FormData();
    form.append('name', name);
    form.append('x', point.x);
    form.append('y', point.y);
    form.append('volume', el.trackVolume.value);
    form.append('autostart', String(el.trackAutostart.checked));
    form.append('looped', String(el.trackLooped.checked));
    form.append('file', file);
    await api(`/api/projects/${state.currentProject.id}/tracks`, { method: 'POST', body: form });
    log(`Трек «${name}» добавлен`);
    await loadProjectById(state.currentProject.id);
  }
});

el.finishPolygonBtn.addEventListener('click', async () => {
  try {
    await savePolygon();
  } catch (error) {
    log(error.message);
  }
});

el.createProjectBtn.addEventListener('click', async () => {
  try {
    const res = await api('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: el.projectName.value, description: el.projectDescription.value }),
    });
    const project = await res.json();
    log(`Проект создан: ${project.name}`);
    await loadProjects();
  } catch (error) {
    log(error.message);
  }
});

el.loadProjectBtn.addEventListener('click', async () => {
  try {
    const id = el.projectSelect.value;
    if (!id) return;
    await loadProjectById(id);
  } catch (error) {
    log(error.message);
  }
});

el.uploadPlanBtn.addEventListener('click', async () => {
  try {
    if (!state.currentProject) throw new Error('Сначала откройте проект');
    const file = el.planFile.files[0];
    if (!file) throw new Error('Выберите файл плана');
    const form = new FormData();
    form.append('file', file);
    await api(`/api/projects/${state.currentProject.id}/plan`, { method: 'POST', body: form });
    log('План загружен');
    await loadProjectById(state.currentProject.id);
  } catch (error) {
    log(error.message);
  }
});

document.querySelectorAll('[data-mode]').forEach((btn) => {
  btn.addEventListener('click', () => setMode(btn.dataset.mode));
});

el.exportBtn.addEventListener('click', () => {
  if (!state.currentProject) {
    log('Сначала откройте проект');
    return;
  }
  window.open(`/api/projects/${state.currentProject.id}/export`, '_blank');
});

loadProjects().catch((e) => log(e.message));
draw();
