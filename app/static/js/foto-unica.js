/* Dropzone de foto única: arquivo, arrastar ou colar (Ctrl+V).
   Mostra a foto atual (na edição) e o preview da nova. Mantém input[name=foto]. */
(function () {
  const campos = document.querySelectorAll('.foto-unica');
  if (!campos.length) return;

  campos.forEach(function (campo) {
    const input = campo.querySelector('.foto-unica-input');
    const zone = campo.querySelector('.foto-unica-zone');
    const grid = campo.querySelector('.foto-unica-grid');
    const atualURL = grid.dataset.atual || '';

    function cardHTML(src, novo) {
      return `
        <div class="foto-card">
          <img src="${src}" alt="">
          ${novo ? '<button type="button" class="foto-del" title="Desfazer">&times;</button>'
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

    zone.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { if (input.files[0]) mostrarNova(input.files[0]); });

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

  // Colar imagem aplica ao primeiro campo de foto única da página.
  document.addEventListener('paste', function (e) {
    const dados = e.clipboardData || window.clipboardData;
    if (!dados) return;
    const campo = document.querySelector('.foto-unica');
    if (!campo) return;
    for (const item of dados.items) {
      if (item.type && item.type.indexOf('image') === 0) {
        const blob = item.getAsFile();
        const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        const file = new File([blob], 'colado-' + Date.now() + '.' + ext, { type: blob.type });
        const input = campo.querySelector('.foto-unica-input');
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        const grid = campo.querySelector('.foto-unica-grid');
        grid.innerHTML = `<div class="foto-card"><img src="${URL.createObjectURL(file)}" alt=""><button type="button" class="foto-del" title="Desfazer">&times;</button></div>`;
        e.preventDefault();
        return;
      }
    }
  });
})();
