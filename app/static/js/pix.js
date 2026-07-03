/* Gerador do Pix "copia e cola" (payload BR Code / EMV).
   Espelho de app/routes.py: _pix_payload / _pix_crc16.
   Um teste (tests/test_pix_js.py) roda este arquivo no Node e compara a saída
   com a do Python — se as duas implementações divergirem, o teste quebra. */
(function (global) {
  function ascii(t, lim) {
    return (t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .toUpperCase().trim().slice(0, lim);
  }
  function emv(tag, val) {
    return tag + String(val.length).padStart(2, '0') + val;
  }
  function crc16(payload) {
    let crc = 0xFFFF;
    for (let i = 0; i < payload.length; i++) {
      crc ^= payload.charCodeAt(i) << 8;
      for (let j = 0; j < 8; j++) {
        crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1);
        crc &= 0xFFFF;
      }
    }
    return crc.toString(16).toUpperCase().padStart(4, '0');
  }
  function payload(chave, nome, cidade, valor, txid) {
    chave = (chave || '').trim();
    if (!chave) return '';
    nome = ascii(nome, 25) || 'RECEBEDOR';
    cidade = ascii(cidade, 15) || 'CIDADE';
    txid = (txid || '***').replace(/[^A-Za-z0-9]/g, '').slice(0, 25) || '***';
    const mai = emv('00', 'br.gov.bcb.pix') + emv('01', chave);
    let campos = emv('00', '01') + emv('26', mai) + emv('52', '0000') + emv('53', '986');
    if (valor && valor > 0) campos += emv('54', Number(valor).toFixed(2));
    campos += emv('58', 'BR') + emv('59', nome) + emv('60', cidade);
    campos += emv('62', emv('05', txid));
    campos += '6304';
    return campos + crc16(campos);
  }
  const api = { payload: payload, crc16: crc16 };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;  // Node (teste)
  global.AtelierPix = api;                                                    // navegador
})(typeof window !== 'undefined' ? window : globalThis);
