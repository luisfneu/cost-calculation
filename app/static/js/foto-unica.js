/* Dropzone de foto única: arquivo, arrastar ou colar (Ctrl+V).
   Mostra a foto atual (na edição) e o preview da nova. Mantém input[name=foto]. */
(function () {
  const campos = document.querySelectorAll('.foto-unica');
  if (!campos.length) return;

  const multi = campos.length > 1;   // só há ambiguidade de "colar" com 2+ campos
  let ativo = campos[0];
  function setAtivo(campo) {
    ativo = campo;
    if (!multi) return;
    campos.forEach(c => c.classList.toggle('foto-unica-ativo', c === campo));
  }

  campos.forEach(function (campo) {
    const input = campo.querySelector('.foto-unica-input');
    const zone = campo.querySelector('.foto-unica-zone');
    const grid = campo.querySelector('.foto-unica-grid');
    const atualURL = grid.dataset.atual || '';

    function cardHTML(src, novo) {
      return `
        <div class="foto-card">
          <img src="${src}" alt="">
          ${novo ? '<button type="button" class="foto-del" title="Desfazer"><i class="bi bi-x-lg"></i></button>'
                 : '<span class="foto-badge">atual</span>'}
        </div>`;
    }
    function mostrarAtual() { grid.innerHTML = atualURL ? cardHTML(atualURL, false) : ''; }
    function mostrarNova(file) { grid.innerHTML = cardHTML(URL.createObjectURL(file), true); }

    function setFile(file) {
      if (!file || file.type.indexOf('image') !== 0) return;
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      mostrarNova(file);
    }
    function limpar() {
      input.value = '';
      mostrarAtual();
    }

    // Marca este campo como alvo do "colar" quando o usuário interage com ele.
    zone.tabIndex = 0;
    zone.addEventListener('mouseenter', () => setAtivo(campo));
    zone.addEventListener('focus', () => setAtivo(campo));
    zone.addEventListener('click', () => { setAtivo(campo); input.click(); });
    input.addEventListener('change', () => { if (input.files[0]) mostrarNova(input.files[0]); });

    campo._colar = setFile;   // usado pelo handler global de paste

    grid.addEventListener('click', e => {
      if (e.target.closest('.foto-del')) limpar();
    });

    ['dragover', 'dragenter'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.add('arrastando');
    }));
    ['dragleave', 'drop'].forEach(ev => zone.addEventListener(ev, e => {
      e.preventDefault(); zone.classList.remove('arrastando');
    }));
    zone.addEventListener('drop', e => { if (e.dataTransfer) setFile(e.dataTransfer.files[0]); });

    mostrarAtual();
  });

  // Colar imagem aplica ao campo ativo (último com hover/foco/clique); com um só
  // campo, sempre nele.
  document.addEventListener('paste', function (e) {
    const dados = e.clipboardData || window.clipboardData;
    if (!dados) return;
    const campo = ativo || campos[0];
    if (!campo || !campo._colar) return;
    for (const item of dados.items) {
      if (item.type && item.type.indexOf('image') === 0) {
        const blob = item.getAsFile();
        const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        const file = new File([blob], 'colado-' + Date.now() + '.' + ext, { type: blob.type });
        campo._colar(file);
        e.preventDefault();
        return;
      }
    }
  });
})();
