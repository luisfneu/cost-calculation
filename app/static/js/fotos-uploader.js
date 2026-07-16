/* Uploader unificado de fotos da peça:
   - adiciona várias imagens por arquivo, arrastar ou colar (Ctrl+V);
   - mostra miniaturas;
   - permite escolher a foto principal (estrela) e remover (×).
   Envia as novas fotos no input[name=fotos] e a escolha em input[name=principal].
   Para as existentes removidas, cria inputs hidden name=remover_existente. */
(function () {
  const uploader = document.getElementById('fotos-uploader');
  if (!uploader) return;

  const input = document.getElementById('fotos-input');
  const grid = document.getElementById('fotos-grid');
  const dropzone = document.getElementById('fotos-dropzone');
  const hidPrincipal = document.getElementById('fotos-principal');
  const boxRemover = document.getElementById('fotos-remover');
  const UPLOADS = window.__UPLOADS_URL || '/static/uploads/';

  let existentes = [];
  try { existentes = JSON.parse(document.getElementById('fotos-existentes').textContent) || []; } catch (e) {}
  const dt = new DataTransfer();   // fotos novas

  function sync() { input.files = dt.files; }

  function tokens() {
    const t = existentes.map(f => 'existente:' + f);
    for (let i = 0; i < dt.files.length; i++) t.push('nova:' + i);
    return t;
  }

  function garantirPrincipal() {
    const ts = tokens();
    if (!ts.includes(hidPrincipal.value)) hidPrincipal.value = ts[0] || '';
  }

  function card(token, src, label) {
    const ehPrincipal = hidPrincipal.value === token;
    const div = document.createElement('div');
    div.className = 'foto-card' + (ehPrincipal ? ' principal' : '');
    div.innerHTML = `
      <img src="${src}" alt="">
      <button type="button" class="foto-star" title="Definir como principal" data-token="${token}">
        <i class="bi ${ehPrincipal ? 'bi-star-fill' : 'bi-star'}"></i>
      </button>
      <button type="button" class="foto-del" title="Remover" data-token="${token}">&times;</button>
      ${ehPrincipal ? '<span class="foto-badge">principal</span>' : ''}`;
    return div;
  }

  function render() {
    garantirPrincipal();
    grid.innerHTML = '';
    existentes.forEach(f => grid.appendChild(card('existente:' + f, UPLOADS + f)));
    for (let i = 0; i < dt.files.length; i++) {
      grid.appendChild(card('nova:' + i, URL.createObjectURL(dt.files[i])));
    }
    sync();
  }

  // Reduz a foto no navegador antes de enviar: no máx. LADO_MAX px, JPEG ~0.85.
  // Fotos de celular (vários MB) chegam leves ao servidor e não estouram o limite
  // nem travam no túnel. Falhou (ex.: HEIC fora do Safari)? envia o original.
  const LADO_MAX = 1600;
  async function redimensionar(file) {
    if (!file.type || file.type.indexOf('image') !== 0) return null;
    if (file.type === 'image/gif') return file;         // preserva animação
    // Arquivo já pequeno: não mexe.
    if (file.size <= 1024 * 1024) return file;
    try {
      const bmp = await createImageBitmap(file);
      const escala = Math.min(1, LADO_MAX / Math.max(bmp.width, bmp.height));
      if (escala >= 1 && file.size <= 3 * 1024 * 1024) { bmp.close && bmp.close(); return file; }
      const w = Math.round(bmp.width * escala), h = Math.round(bmp.height * escala);
      const canvas = document.createElement('canvas');
      canvas.width = w; canvas.height = h;
      canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
      bmp.close && bmp.close();
      const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.85));
      if (!blob) return file;
      const base = (file.name || 'foto').replace(/\.[^.]+$/, '');
      return new File([blob], base + '.jpg', { type: 'image/jpeg' });
    } catch (e) {
      return file;   // não conseguiu decodificar: manda o original (servidor tem folga)
    }
  }

  async function addFiles(fileList) {
    const arquivos = Array.from(fileList);
    for (const f of arquivos) {
      const r = await redimensionar(f);
      if (r) dt.items.add(r);
    }
    render();
  }

  function removerNova(idx) {
    const novo = new DataTransfer();
    for (let i = 0; i < dt.files.length; i++) if (i !== idx) novo.items.add(dt.files[i]);
    dt.items.clear();
    for (const f of novo.files) dt.items.add(f);
    render();
  }

  function removerExistente(nome) {
    existentes = existentes.filter(f => f !== nome);
    const h = document.createElement('input');
    h.type = 'hidden'; h.name = 'remover_existente'; h.value = nome;
    boxRemover.appendChild(h);
    render();
  }

  // ---- eventos ----
  dropzone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => { addFiles(input.files); });

  grid.addEventListener('click', e => {
    const star = e.target.closest('.foto-star');
    if (star) { hidPrincipal.value = star.dataset.token; render(); return; }
    const del = e.target.closest('.foto-del');
    if (del) {
      const tk = del.dataset.token;
      if (tk.startsWith('nova:')) removerNova(parseInt(tk.split(':')[1], 10));
      else removerExistente(tk.slice('existente:'.length));
    }
  });

  ['dragover', 'dragenter'].forEach(ev => dropzone.addEventListener(ev, e => {
    e.preventDefault(); dropzone.classList.add('arrastando');
  }));
  ['dragleave', 'drop'].forEach(ev => dropzone.addEventListener(ev, e => {
    e.preventDefault(); dropzone.classList.remove('arrastando');
  }));
  dropzone.addEventListener('drop', e => { if (e.dataTransfer) addFiles(e.dataTransfer.files); });

  document.addEventListener('paste', e => {
    const dados = e.clipboardData || window.clipboardData;
    if (!dados) return;
    for (const item of dados.items) {
      if (item.type && item.type.indexOf('image') === 0) {
        const blob = item.getAsFile();
        const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        const file = new File([blob], 'colado-' + Date.now() + '.' + ext, { type: blob.type });
        addFiles([file]);
        e.preventDefault();
        return;
      }
    }
  });

  render();
})();
