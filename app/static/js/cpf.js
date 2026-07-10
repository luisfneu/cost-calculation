// Máscara + validação de CPF em inputs com data-cpf. Mesma regra do servidor
// (dígitos verificadores). Marca is-invalid quando preenchido e inválido.
(function () {
  function so_digitos(s) { return (s || '').replace(/\D/g, '').slice(0, 11); }

  function mascarar(d) {
    let out = d;
    if (d.length > 9) out = d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6, 9) + '-' + d.slice(9);
    else if (d.length > 6) out = d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6);
    else if (d.length > 3) out = d.slice(0, 3) + '.' + d.slice(3);
    return out;
  }

  function valido(cpf) {
    const d = so_digitos(cpf);
    if (!d) return true;                     // vazio = ok (opcional)
    if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
    for (const i of [9, 10]) {
      let soma = 0;
      for (let n = 0; n < i; n++) soma += parseInt(d[n]) * ((i + 1) - n);
      let dv = (soma * 10) % 11;
      if (dv === 10) dv = 0;
      if (dv !== parseInt(d[i])) return false;
    }
    return true;
  }

  document.querySelectorAll('input[data-cpf]').forEach(function (el) {
    el.value = mascarar(so_digitos(el.value));
    el.addEventListener('input', function () {
      const pos = el.selectionEnd;
      el.value = mascarar(so_digitos(el.value));
      el.setSelectionRange(el.value.length, el.value.length);
      void pos;
    });
    el.addEventListener('blur', function () {
      el.classList.toggle('is-invalid', !valido(el.value));
    });
  });
})();
