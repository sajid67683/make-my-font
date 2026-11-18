(() => {
  "use strict";

  const MAX_FILES = 6;
  const MAX_SIDE = 2400; // px; photos are shrunk in the browser before upload
  const UPLOAD_BUDGET = 4.2 * 1024 * 1024; // Vercel functions accept ~4.5 MB bodies

  const $ = (id) => document.getElementById(id);
  const fileInput = $("file-input");
  const drop = $("drop");
  const list = $("file-list");
  const form = $("settings");
  const genBtn = $("generate");
  const status = $("status");

  let items = []; // { id, name, blob, url }
  let nextId = 1;
  let fontCounter = 0;
  let downloadUrl = null;
  let charsetPages = null;

  fetch("/api/charset").then((r) => r.json()).then((j) => (charsetPages = j.pages)).catch(() => {});

  // ---------- range outputs ----------
  form.querySelectorAll("input[type=range][data-out]").forEach((r) => {
    const out = $(r.dataset.out);
    const fixed = Number(r.dataset.fixed || 0);
    const sync = () => (out.textContent = Number(r.value).toFixed(fixed));
    r.addEventListener("input", sync);
    sync();
  });

  // ---------- image intake ----------
  async function loadBitmap(file) {
    try {
      return await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch {
      // Fallback for browsers without createImageBitmap options
      const url = URL.createObjectURL(file);
      try {
        const img = new Image();
        img.src = url;
        await img.decode();
        return img;
      } finally {
        URL.revokeObjectURL(url);
      }
    }
  }

  async function shrink(file, maxSide, quality) {
    const bmp = await loadBitmap(file);
    const w = bmp.width, h = bmp.height;
    const f = Math.min(1, maxSide / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * f);
    canvas.height = Math.round(h * f);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    if (bmp.close) bmp.close();
    return new Promise((res, rej) =>
      canvas.toBlob((b) => (b ? res(b) : rej(new Error("encode failed"))), "image/jpeg", quality)
    );
  }

  async function addFiles(fileList) {
    const files = [...fileList].filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic)$/i.test(f.name));
    if (!files.length) return;
    const room = MAX_FILES - items.length;
    if (room <= 0) return setStatus(`You can upload up to ${MAX_FILES} images.`, true);
    setStatus("Preparing images…");
    for (const file of files.slice(0, room)) {
      try {
        const blob = await shrink(file, MAX_SIDE, 0.9);
        items.push({ id: nextId++, name: file.name, file, blob, url: URL.createObjectURL(blob) });
      } catch {
        setStatus(`Couldn't read ${file.name}. Try a JPG or PNG.`, true);
      }
    }
    if (files.length > room) setStatus(`Only the first ${MAX_FILES} images were kept.`, true);
    else setStatus("");
    renderFiles();
  }

  function renderFiles() {
    list.innerHTML = "";
    for (const it of items) {
      const li = document.createElement("li");
      li.innerHTML = `<img alt="" /><span class="name"></span><button type="button" aria-label="Remove">×</button>`;
      li.querySelector("img").src = it.url;
      li.querySelector(".name").textContent = it.name;
      li.querySelector("button").onclick = () => {
        URL.revokeObjectURL(it.url);
        items = items.filter((x) => x !== it);
        renderFiles();
      };
      list.appendChild(li);
    }
    genBtn.disabled = items.length === 0;
  }

  fileInput.addEventListener("change", () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  });
  ["dragenter", "dragover"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); })
  );
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  // keep total upload under the serverless body limit
  async function uploadBlobs() {
    let blobs = items.map((it) => it.blob);
    const total = () => blobs.reduce((s, b) => s + b.size, 0);
    let side = MAX_SIDE, q = 0.85;
    while (total() > UPLOAD_BUDGET && side > 1200) {
      side -= 300; q = Math.max(0.7, q - 0.05);
      blobs = await Promise.all(items.map((it) => shrink(it.file, side, q)));
    }
    return blobs;
  }

  // ---------- generate ----------
  function setStatus(msg, isError = false) {
    status.textContent = msg;
    status.classList.toggle("error", isError);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!items.length) return;
    genBtn.disabled = true;
    genBtn.classList.add("busy");
    const t0 = performance.now();
    const tick = setInterval(() => {
      const s = ((performance.now() - t0) / 1000).toFixed(0);
      setStatus(`Straightening pages and tracing letters… ${s}s`);
    }, 500);

    try {
      const fd = new FormData(form);
      fd.set("normalize", form.normalize.checked ? "1" : "0");
      fd.set("fill_case", form.fill_case.checked ? "1" : "0");
      const blobs = await uploadBlobs();
      blobs.forEach((b, i) => fd.append("files", b, items[i].name.replace(/\.\w+$/, "") + ".jpg"));

      const res = await fetch("/api/generate", { method: "POST", body: fd });
      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error(res.status === 413 ? "Photos are too large. Try fewer or smaller images." : `Server error (${res.status}). Please try again.`);
      }
      if (!data.ok) {
        if (data.sheets) renderSheets(data.sheets);
        throw new Error(data.error || "Something went wrong.");
      }
      await showResult(data);
      setStatus(`Done in ${data.seconds}s.`);
    } catch (err) {
      setStatus(err.message || String(err), true);
    } finally {
      clearInterval(tick);
      genBtn.disabled = items.length === 0;
      genBtn.classList.remove("busy");
    }
  });

  // ---------- result ----------
  function b64ToBytes(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  }

  async function showResult(data) {
    const bytes = b64ToBytes(data.font);
    const family = `MMF-preview-${++fontCounter}`;
    const face = new FontFace(family, bytes.buffer);
    await face.load();
    document.fonts.add(face);
    const stack = `"${family}", sans-serif`;

    if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    downloadUrl = URL.createObjectURL(new Blob([bytes], { type: "font/ttf" }));
    const dl = $("download");
    dl.href = downloadUrl;
    dl.download = data.filename;

    $("result-title").textContent = `“${data.family}” is ready`;
    const nBorrowed = Object.keys(data.borrowed).length;
    const parts = [`${data.found.length} characters traced`];
    if (nBorrowed) parts.push(`${nBorrowed} borrowed from the other case`);
    if (data.missing.length) parts.push(`${data.missing.length} missing`);
    $("result-summary").textContent = parts.join(" · ") + ". Click the preview to type your own text.";

    $("preview-text").style.fontFamily = stack;
    renderCharset(data, stack);
    renderSheets(data.sheets);

    const section = $("result");
    section.hidden = false;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderCharset(data, stack) {
    const all = charsetPages ? charsetPages.join("") : data.found + Object.keys(data.borrowed).join("") + data.missing;
    const grid = $("charset");
    grid.innerHTML = "";
    grid.style.fontFamily = stack;
    for (const ch of all) {
      const d = document.createElement("div");
      d.textContent = ch;
      d.dataset.c = ch;
      if (data.borrowed[ch]) { d.className = "borrowed"; d.title = `borrowed from “${data.borrowed[ch]}”`; }
      else if (data.missing.includes(ch)) { d.className = "missing"; d.title = "missing"; }
      grid.appendChild(d);
    }
  }

  function renderSheets(sheets) {
    const box = $("sheets");
    box.innerHTML = "";
    for (const s of sheets) {
      const div = document.createElement("div");
      div.className = "sheet";
      if (s.ok) {
        const img = document.createElement("img");
        img.src = s.preview;
        img.alt = `Detected page ${s.page}`;
        div.appendChild(img);
        div.append(`${s.file}: page ${s.page}, ${s.chars} characters`);
        for (const w of s.warnings || []) {
          const p = document.createElement("div");
          p.className = "warn";
          p.textContent = w;
          div.appendChild(p);
        }
      } else {
        const p = document.createElement("div");
        p.className = "err";
        p.textContent = `${s.file}: ${s.error}`;
        div.appendChild(p);
      }
      box.appendChild(div);
    }
  }

  const sizeSlider = $("preview-size");
  sizeSlider.addEventListener("input", () => ($("preview-text").style.fontSize = sizeSlider.value + "px"));
})();
