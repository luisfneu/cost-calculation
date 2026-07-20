// Provador virtual (recomendador de tamanho) — 100% no navegador.
// Passo 1: altura/peso → chute inicial. Passo 2: ajusta busto/cintura/quadril
// numa silhueta 2D. Resultado: tamanho recomendado + caimento, casando as medidas
// do corpo com a tabela da peça (window.SH_PROVADOR).
(function () {
  const CFG = window.SH_PROVADOR;
  const modal = document.getElementById('modal-provador');
  if (!CFG || !modal) return;

  const SCALE = 0.42;          // cm de meia-circunferência → px na silhueta
  const CX = 100;
  const $ = id => modal.querySelector(id);

  // ---- tabela efetiva: padrão + o que a peça sobrescreve ----
  function chartEfetivo() {
    const porTam = {};
    (CFG.peca || []).forEach(r => { porTam[r.tam] = r; });
    return (CFG.padrao || []).map(p => {
      const o = porTam[p.tam] || {};
      return {
        tam: p.tam,
        busto: Number(o.busto) || p.busto,
        cintura: Number(o.cintura) || p.cintura,
        quadril: Number(o.quadril) || p.quadril,
      };
    });
  }
  const CHART = chartEfetivo();
  // Medidas relevantes pela zona da peça (superior/inferior/inteiro).
  const MEDS = (Array.isArray(CFG.medidas) && CFG.medidas.length)
    ? CFG.medidas : ['busto', 'cintura', 'quadril'];
  // Esconde os sliders que não contam para esta peça.
  modal.querySelectorAll('[data-medida]').forEach(el => {
    if (!MEDS.includes(el.dataset.medida)) el.hidden = true;
  });

  // ---- estado do corpo (cm) ----
  const corpo = { busto: 96, cintura: 78, quadril: 106 };

  function estimarInicial(altura, peso) {
    const bandas = [[52, 'PP'], [60, 'P'], [70, 'M'], [80, 'G'], [999, 'GG']];
    let tam = 'M';
    for (const [lim, t] of bandas) { if (peso <= lim) { tam = t; break; } }
    // altura alta afina um tom; baixa engorda um tom (nudge leve)
    const row = CHART.find(r => r.tam === tam) || CHART[2];
    let b = row.busto, c = row.cintura, q = row.quadril;
    if (altura && altura >= 175) { b -= 2; c -= 2; q -= 2; }
    else if (altura && altura <= 155) { b += 2; c += 2; q += 2; }
    return { busto: b, cintura: c, quadril: q };
  }

  // ---- silhueta (path fechado suave por Catmull-Rom) ----
  function smooth(points) {
    const n = points.length;
    let d = 'M' + points[0][0] + ',' + points[0][1];
    for (let i = 0; i < n; i++) {
      const p0 = points[(i - 1 + n) % n], p1 = points[i], p2 = points[(i + 1) % n], p3 = points[(i + 2) % n];
      const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
      const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ' C' + c1x + ',' + c1y + ' ' + c2x + ',' + c2y + ' ' + p2[0] + ',' + p2[1];
    }
    return d + 'Z';
  }
  // ---- silhueta animada: deformação direcional por região ----
  // Perfil olhando p/ a ESQUERDA: busto cresce só p/ frente (esquerda) e ganha
  // volume vertical; cintura mexe no centro (os dois lados); quadril cresce
  // mais p/ trás (direita) e engrossa a perna junto.
  const REF = { busto: 96, cintura: 78, quadril: 106 };   // referência = tamanho M
  const canvas = $('#sil-canvas');
  const W = canvas ? canvas.width : 0, H = canvas ? canvas.height : 0;
  const img = new Image();
  let imgOk = false;
  let off = null;                       // silhueta sem distorção, já no tamanho do canvas
  let lArr = [], rArr = [];             // borda esquerda/direita do corpo por linha
  let tBusto = 0.31, tCintura = 0.44, tQuadril = 0.56;   // detectados no SVG

  function analisar() {
    off = document.createElement('canvas');
    off.width = W; off.height = H;
    const octx = off.getContext('2d');
    const sW = img.naturalWidth || 512, sH = img.naturalHeight || 512;
    const baseW = H * sW / sH, baseX = (W - baseW) / 2;
    octx.drawImage(img, baseX, 0, baseW, H);
    const px = octx.getImageData(0, 0, W, H).data;
    lArr = new Array(H).fill(-1); rArr = new Array(H).fill(-1);
    const larg = new Array(H).fill(0);
    for (let y = 0; y < H; y++) {
      let l = -1, r = -1;
      for (let x = 0; x < W; x++) {
        if (px[(y * W + x) * 4 + 3] > 25) { if (l < 0) l = x; r = x; }
      }
      if (l >= 0) { lArr[y] = l; rArr[y] = r; larg[y] = r - l; }
    }
    const pico = (t0, t1, min) => {
      let melhor = min ? 1e9 : -1, ty = (t0 + t1) / 2;
      for (let y = Math.floor(t0 * H); y < Math.floor(t1 * H); y++) {
        if (larg[y] <= 0) continue;
        if ((min && larg[y] < melhor) || (!min && larg[y] > melhor)) { melhor = larg[y]; ty = y / H; }
      }
      return ty;
    };
    tBusto = pico(0.18, 0.40, false);              // pico do tronco superior
    tQuadril = pico(tBusto + 0.08, 0.66, false);   // pico do quadril/bumbum
    // Cintura: o ponto mais estreito ENTRE busto e quadril (centro do tronco).
    tCintura = pico(tBusto + 0.03, tQuadril - 0.03, true);
  }

  if (canvas) {
    img.onload = () => { analisar(); imgOk = true; desenhar(); };
    img.src = canvas.dataset.src;
  }

  // Desvio relativo do M (−0.5 a +0.6), com ganho p/ ficar visível.
  // Medida fora da zona da peça não anima (fica no corpo de referência).
  function delta(m) {
    if (!MEDS.includes(m)) return 0;
    return Math.max(-0.5, Math.min(0.6, (corpo[m] - REF[m]) / REF[m] * 1.6));
  }
  const gauss = (t, t0, sig) => Math.exp(-((t - t0) * (t - t0)) / (2 * sig * sig));

  function desenhar() {
    ['busto', 'cintura', 'quadril'].forEach(m => {
      const el = $('#val-' + m); if (el) el.textContent = corpo[m] + ' cm';
    });
    if (!canvas || !imgOk) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    const dB = delta('busto'), dW = delta('cintura'), dH = delta('quadril');
    // Busto maior também ganha volume vertical (a faixa alarga).
    const sigB = 0.055 * (1 + Math.max(0, dB) * 1.2);
    for (let y = 0; y < H; y++) {
      const l = lArr[y], r = rArr[y];
      if (l < 0 || r <= l) { ctx.drawImage(off, 0, y, W, 1, 0, y, W, 1); continue; }
      const t = y / H, hw = (r - l) / 2;
      const wB = gauss(t, tBusto, sigB);
      const wW = gauss(t, tCintura, 0.05);
      const wH = gauss(t, tQuadril, 0.055);
      // Perna: platô suave abaixo do quadril até o tornozelo.
      let wLeg = 0;
      const ini = tQuadril + 0.05;
      if (t > ini) {
        const entrada = Math.min(1, (t - ini) / 0.06);
        const saida = Math.max(0, 1 - Math.max(0, t - 0.86) / 0.11);
        wLeg = entrada * saida;
      }
      // Deslocamento de cada borda (px). dL>0 empurra a frente p/ fora.
      let dL = 0, dR = 0;
      dL += dB * hw * wB;                              // busto: só a frente
      dL += dW * hw * wW; dR += dW * hw * wW;          // cintura: centro (2 lados)
      dR += dH * hw * wH;                              // quadril: p/ trás
      dL += dH * hw * wH * 0.25;                       // leve na frente do quadril
      const g = dH * hw * wLeg * 0.4;                  // perna engrossa junto
      dL += g; dR += g;
      const s = ((r - l) + dL + dR) / (r - l);         // mapeia [l,r] → [l−dL, r+dR]
      const a = (l - dL) - l * s;
      ctx.drawImage(off, 0, y, W, 1, a, y, W * s, 1);
    }
  }

  // ---- recomendação (só as medidas relevantes da zona da peça) ----
  function recomendar() {
    const medidas = MEDS;
    let idx = 0, binding = medidas[0];
    medidas.forEach(m => {
      let i = CHART.findIndex(row => row[m] > 0 && row[m] >= corpo[m]);
      if (i < 0) i = CHART.length - 1;      // excede tudo → maior tamanho
      if (i > idx) { idx = i; binding = m; }
    });
    const row = CHART[idx];
    const gap = row[binding] - corpo[binding];
    let caimento, cor;
    if (gap < 0) { caimento = 'pode ficar justo'; cor = '#c0392b'; }
    else if (gap < 3) { caimento = 'justo'; cor = '#b8860b'; }
    else if (gap <= 9) { caimento = 'ideal'; cor = '#1a7f37'; }
    else { caimento = 'folgado'; cor = '#b8860b'; }
    return { tam: row.tam, caimento, cor, binding };
  }

  // ---- passos ----
  function irPara(passo) {
    modal.querySelectorAll('[data-passo]').forEach(p => { p.hidden = p.dataset.passo !== String(passo); });
  }

  // passo 1 → 2
  $('#pv-proximo').addEventListener('click', () => {
    const altura = parseFloat($('#pv-altura').value) || 0;
    const peso = parseFloat($('#pv-peso').value) || 0;
    if (peso < 30 || peso > 200 || altura < 120 || altura > 210) {
      $('#pv-erro1').textContent = 'Informe altura (cm) e peso (kg) válidos.'; return;
    }
    $('#pv-erro1').textContent = '';
    const est = estimarInicial(altura, peso);
    ['busto', 'cintura', 'quadril'].forEach(m => {
      const [lo, hi] = LIM[m];
      corpo[m] = Math.min(hi, Math.max(lo, Math.round(est[m])));
    });
    syncSliders(); desenhar(); irPara(2);
  });
  $('#pv-voltar2').addEventListener('click', () => irPara(1));

  // Ajuste das medidas: slider (arrastar) + botões − / + (fino), sincronizados.
  // Faixa vem da TABELA DA PEÇA: mínimo = menor tamanho; máximo = maior tamanho
  // + uma tolerância igual ao salto entre os tamanhos (ex.: 110→116 ⇒ máx 122).
  function limites(m) {
    const vals = CHART.map(r => Number(r[m])).filter(v => v > 0).sort((a, b) => a - b);
    if (vals.length < 2) return { busto: [74, 130], cintura: [56, 122], quadril: [80, 142] }[m];
    const salto = vals[vals.length - 1] - vals[vals.length - 2];
    return [vals[0], vals[vals.length - 1] + salto];
  }
  const LIM = { busto: limites('busto'), cintura: limites('cintura'), quadril: limites('quadril') };
  // Aplica a faixa nos sliders (o HTML traz uma faixa genérica).
  ['busto', 'cintura', 'quadril'].forEach(m => {
    const s = modal.querySelector('input[data-slider="' + m + '"]');
    if (s) { s.min = LIM[m][0]; s.max = LIM[m][1]; }
  });
  function setMedida(m, val) {
    const [lo, hi] = LIM[m];
    corpo[m] = Math.min(hi, Math.max(lo, Math.round(val)));
    const s = modal.querySelector('input[data-slider="' + m + '"]');
    if (s) s.value = corpo[m];
    desenhar();
  }
  function syncSliders() {
    ['busto', 'cintura', 'quadril'].forEach(m => {
      const s = modal.querySelector('input[data-slider="' + m + '"]');
      if (s) s.value = corpo[m];
    });
  }
  modal.querySelectorAll('input[data-slider]').forEach(s => {
    s.addEventListener('input', () => setMedida(s.dataset.slider, s.value));
  });
  modal.querySelectorAll('[data-ajuste]').forEach(btn => {
    btn.addEventListener('click', () => setMedida(btn.dataset.ajuste, corpo[btn.dataset.ajuste] + Number(btn.dataset.delta)));
  });

  // ver resultado
  $('#pv-ver').addEventListener('click', () => {
    const r = recomendar();
    $('#pv-tam').textContent = r.tam;
    const cai = $('#pv-caimento'); cai.textContent = 'caimento ' + r.caimento; cai.style.color = r.cor;
    const base = $('#pv-base');
    if (base) base.textContent = 'decidido pela medida do ' + r.binding;
    irPara(3);
  });
  $('#pv-refazer').addEventListener('click', () => irPara(2));

  // pré-seleciona o tamanho na página ao aplicar
  const aplicar = $('#pv-aplicar');
  if (aplicar) aplicar.addEventListener('click', () => {
    const tam = $('#pv-tam').textContent;
    const chip = document.querySelector('.tam-chip[data-tam="' + tam + '"]');
    if (chip) chip.click();
    bootstrap.Modal.getOrCreateInstance(modal).hide();
  });

  modal.addEventListener('show.bs.modal', () => { irPara(1); });
})();
