// Desenho da etiqueta no canvas — compartilhado entre a etiqueta individual e a
// impressão em lote. Depende de qrcode.min.js (QRCode global).
// Uso: desenharEtiqueta(canvas, {sku, nome, colecao, preco, tam}, monoImg, qrBox)
(function () {
  const GOLD = "#b08a4f", INK = "#2c2620", MUTE = "#6b5f52";
  const DPR = 3, W = 300, H = 500;   // design 300×500 (30×50mm); backing 3×
  window.ETIQUETA_DIM = { DPR, W, H };

  function conteudoQR(sku, tam) { return tam ? `${sku}--${tam}` : sku; }

  function qrCanvas(qrBox, texto) {
    qrBox.innerHTML = '';
    new QRCode(qrBox, { text: texto || ' ', width: 240, height: 240,
                        colorDark: INK, colorLight: "#ffffff" });
    return qrBox.querySelector('canvas');
  }

  function espacado(ctx, txt, cx, y, sp) {
    const larg = [...txt].reduce((a, c) => a + ctx.measureText(c).width + sp, -sp);
    let x = cx - larg / 2;
    ctx.textAlign = "left";
    for (const c of txt) { ctx.fillText(c, x, y); x += ctx.measureText(c).width + sp; }
    ctx.textAlign = "center";
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  window.desenharEtiqueta = function (canvas, dados, monoImg, qrBox) {
    const ctx = canvas.getContext('2d');
    const sku = dados.sku || '', nome = dados.nome || '', colecao = dados.colecao || '';
    const preco = dados.preco || '', tam = dados.tam || '';
    const texto = conteudoQR(sku, tam);

    ctx.save();
    ctx.scale(DPR, DPR);
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, W, H);

    ctx.strokeStyle = "#c9a96a"; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
    ctx.strokeRect(6, 6, W - 12, H - 12); ctx.setLineDash([]);
    ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";

    if (monoImg && monoImg.width) {
      const h = 88, w = monoImg.width / monoImg.height * h;
      ctx.drawImage(monoImg, (W - w) / 2, 30, w, h);
    }
    ctx.fillStyle = INK;
    ctx.font = '600 20px "Cormorant Garamond", serif';
    espacado(ctx, "SABRINA HANSEN", W / 2, 150, 3);
    ctx.fillStyle = GOLD;
    ctx.font = '11px "Jost", sans-serif';
    espacado(ctx, "ATELIER", W / 2, 168, 4);

    let fs = 24;
    ctx.fillStyle = INK;
    const maxW = W - 50;
    do { ctx.font = `600 ${fs}px "Cormorant Garamond", serif`; fs -= 1; }
    while (ctx.measureText(nome).width > maxW && fs > 12);
    const nomeW = ctx.measureText(nome).width;

    ctx.font = 'bold 12px "Jost", sans-serif';
    const bW = tam ? ctx.measureText(tam).width + 18 : 0;
    const grupoW = nomeW + (tam ? bW + 8 : 0);
    const x0 = (W - grupoW) / 2, nomeY = 222;

    ctx.textAlign = "left";
    ctx.fillStyle = INK;
    ctx.font = `600 ${fs + 1}px "Cormorant Garamond", serif`;
    ctx.fillText(nome, x0, nomeY);
    if (tam) {
      const bx = x0 + nomeW + 8, by = nomeY - 15, bh = 20;
      ctx.fillStyle = GOLD;
      roundRect(ctx, bx, by, bW, bh, 5); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = 'bold 12px "Jost", sans-serif';
      ctx.textAlign = "center";
      ctx.fillText(tam, bx + bW / 2, by + 14);
    }
    ctx.textAlign = "center";

    if (colecao) {
      ctx.fillStyle = MUTE; ctx.font = '14px "Cormorant Garamond", serif';
      ctx.fillText(colecao, W / 2, 246);
    }
    ctx.fillStyle = GOLD; ctx.font = '500 26px "Jost", sans-serif';
    ctx.fillText(preco, W / 2, 288);

    const qc = qrCanvas(qrBox, texto);
    const qs = 140, qx = (W - qs) / 2, qy = 310;
    if (qc) ctx.drawImage(qc, qx, qy, qs, qs);

    ctx.fillStyle = MUTE; ctx.font = '12px "Jost", sans-serif';
    ctx.fillText(texto, W / 2, qy + qs + 24);

    ctx.restore();
  };
})();
