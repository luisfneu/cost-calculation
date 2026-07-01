/* Permite anexar imagem em qualquer campo .foto-campo por:
   - seleção de arquivo (input padrão), ou
   - colar do clipboard (Ctrl+V) — ex.: print de tela.
   Mostra preview e injeta o arquivo colado no <input type=file> via DataTransfer. */
(function () {
  function injetarArquivo(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
  }

  function mostrarPreview(campo, src) {
    let img = campo.querySelector('.foto-preview');
    if (!img) {
      img = document.createElement('img');
      img.className = 'foto-preview foto-thumb mt-2';
      campo.appendChild(img);
    }
    img.src = src;
    img.style.display = 'inline-block';
  }

  document.addEventListener('DOMContentLoaded', function () {
    const campos = document.querySelectorAll('.foto-campo');
    if (!campos.length) return;

    // Atualiza preview quando um arquivo é escolhido manualmente.
    campos.forEach(function (campo) {
      const input = campo.querySelector('input[type="file"]');
      if (!input) return;
      input.addEventListener('change', function () {
        if (input.files && input.files[0]) {
          mostrarPreview(campo, URL.createObjectURL(input.files[0]));
        }
      });
    });

    // Colar imagem do clipboard em qualquer lugar da página aplica ao 1º campo de foto.
    document.addEventListener('paste', function (e) {
      const dados = e.clipboardData || window.clipboardData;
      if (!dados) return;
      for (const item of dados.items) {
        if (item.type && item.type.indexOf('image') === 0) {
          const blob = item.getAsFile();
          const ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
          const file = new File([blob], 'colado-' + Date.now() + '.' + ext, { type: blob.type });
          const campo = document.querySelector('.foto-campo');
          const input = campo.querySelector('input[type="file"]');
          injetarArquivo(input, file);
          mostrarPreview(campo, URL.createObjectURL(file));
          const aviso = campo.querySelector('.foto-colada-ok');
          if (aviso) aviso.style.display = 'inline';
          e.preventDefault();
          return;
        }
      }
    });
  });
})();
