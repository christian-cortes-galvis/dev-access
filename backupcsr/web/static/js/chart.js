/* Gráficos SVG propios (sin librerías): sparkline de tamaño y barras de duración. */

function clean(values) {
  return values.filter((v) => typeof v === 'number' && isFinite(v));
}

function shortDate(value) {
  const d = new Date(value);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString('es-CO', { day: '2-digit', month: 'short' });
}

function fmtGb(bytes) {
  return (Number(bytes || 0) / (1024 ** 3)).toFixed(2) + ' GB';
}

export function emptyChart(text) {
  return '<div class="chart-empty">' + (text || 'sin datos') + '</div>';
}

/** points: [{t, v}] ordenados por t. */
export function sparkline(points) {
  if (!points || points.length < 2) return emptyChart('sin histórico suficiente');
  const W = 320, H = 64, padX = 4, padY = 8;
  const values = clean(points.map((p) => Number(p.v)));
  if (!values.length) return emptyChart('sin datos de tamaño');
  const max = Math.max.apply(null, values);
  const min = Math.min.apply(null, values);
  const span = (max - min) || max || 1;
  const step = (W - padX * 2) / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = padX + i * step;
    const y = padY + (H - padY * 2) * (1 - ((Number(p.v) - min) / span));
    return [x, y];
  });
  const line = coords.map((c, i) => (i ? 'L' : 'M') + c[0].toFixed(1) + ' ' + c[1].toFixed(1)).join(' ');
  const area = line + ' L' + coords[coords.length - 1][0].toFixed(1) + ' ' + (H - padY) +
    ' L' + coords[0][0].toFixed(1) + ' ' + (H - padY) + ' Z';
  const grid = [0.25, 0.5, 0.75].map((f) =>
    '<line class="grid" x1="' + padX + '" y1="' + (padY + (H - padY * 2) * f).toFixed(1) +
    '" x2="' + (W - padX) + '" y2="' + (padY + (H - padY * 2) * f).toFixed(1) + '"/>'
  ).join('');
  const first = shortDate(points[0].t);
  const last = shortDate(points[points.length - 1].t);
  return '<svg class="spark" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img">' +
    grid +
    '<path class="area" d="' + area + '"/>' +
    '<path class="line" d="' + line + '"/>' +
    '<text class="label" x="' + padX + '" y="' + (H - 1) + '">' + first + '</text>' +
    '<text class="label" x="' + (W - padX) + '" y="' + (H - 1) + '" text-anchor="end">' + last + '</text>' +
    '</svg>' +
    '<div class="d-flex justify-content-between small muted mt-1">' +
    '<span>mín ' + fmtGb(min) + '</span><span>máx ' + fmtGb(max) + '</span></div>';
}

/** items: [{label, value}] value en segundos. */
export function barList(items, formatter) {
  if (!items || !items.length) return emptyChart('sin ejecuciones');
  const max = Math.max.apply(null, items.map((i) => Number(i.value) || 0)) || 1;
  const rows = items.map((item) => {
    const pct = Math.max(2, Math.round((Number(item.value) || 0) * 100 / max));
    return '<div class="mb-2">' +
      '<div class="d-flex justify-content-between small"><span>' + item.label + '</span>' +
      '<span class="muted">' + formatter(item.value) + '</span></div>' +
      '<div class="progress" style="height:6px"><div class="progress-bar" role="progressbar" ' +
      'style="width:' + pct + '%" aria-valuenow="' + pct + '" aria-valuemin="0" aria-valuemax="100"></div></div>' +
      '</div>';
  }).join('');
  return rows;
}

/**
 * Anillo de uso del disco. `percent` es el uso total y `copiesPercent` la parte
 * de ese uso ocupada por las copias (se pinta en otro color, contigua al inicio).
 */
export function diskGauge(percent, level, copiesPercent) {
  const radius = 52;
  const length = 2 * Math.PI * radius;
  const clamp = (value) => Math.max(0, Math.min(100, Number(value) || 0));
  const used = clamp(percent);
  const copies = Math.min(clamp(copiesPercent), used);
  const usedArc = (used / 100) * length;
  const copiesArc = (copies / 100) * length;
  const arc = (cls, value, offset) => {
    const arcLength = Math.min(value, length);
    return '<circle class="disk-value ' + cls + '" cx="60" cy="60" r="' + radius +
      '" stroke-dasharray="' + arcLength.toFixed(1) + ' ' + (length - arcLength).toFixed(1) + '"' +
      (offset ? ' stroke-dashoffset="-' + offset.toFixed(1) + '"' : '') + '/>';
  };
  const arcs = copiesArc > 0.5
    ? arc('disk-copies', copiesArc) + (usedArc - copiesArc > 0.5 ? arc('disk-used', usedArc - copiesArc, copiesArc) : '')
    : arc('disk-used', usedArc);
  return '<svg class="disk-svg' + (copiesArc > 0.5 ? ' disk-has-copies' : '') + '" viewBox="0 0 120 120" ' +
    'role="img" aria-label="' + used.toFixed(1) + '% de uso">' +
    '<circle class="disk-track" cx="60" cy="60" r="' + radius + '"/>' + arcs + '</svg>';
}

/** items: [{label, value}] value en bytes. */
export function sizeBarList(items) {
  return barList(
    items.map((i) => ({ label: i.label, value: i.value })),
    (v) => fmtGb(v)
  );
}
