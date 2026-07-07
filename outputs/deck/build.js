/* RigVision-3D — Board Presentation (8 slides)
   Restrained corporate look: charcoal + grayscale, single muted RigVision-maroon accent,
   hairline tables, plain monochrome flowchart, real screenshots. No gradients. */
const pptxgen = require("pptxgenjs");

// ── Palette: Charcoal Minimal, one accent ─────────────────────────
const INK    = "222A30";  // charcoal — dark slides + headings
const INK2   = "2C353C";  // raised panel on dark
const TXT    = "2B333A";  // body text on light
const MUTED  = "6E7A85";  // muted gray
const MUTEDD = "9BA6AF";  // muted on dark
const LIGHT  = "FFFFFF";
const PANEL  = "F2F4F6";  // card on light
const PANEL2 = "EBEEF1";
const LINE   = "D3D9DF";  // hairline
const ACCENT = "8C2B2F";  // muted RigVision maroon — used sparingly only
const SCRIM  = "1A2025";

const HEAD = "Georgia";
const BODY = "Calibri";

const SHOTS = "C:/Users/Satvik/Desktop/RigVision/docs/screenshots";
const SHOT_AR = 2560 / 1490; // ~1.718

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Team RigVision · LNMIIT";
pres.title = "RigVision-3D";

const W = 10, H = 5.625, M = 0.55;

// ── helpers ───────────────────────────────────────────────────────
function pageNum(slide, n, dark) {
  slide.addText(
    [{ text: `${n}`, options: { color: ACCENT, bold: true } },
     { text: ` / 8`, options: { color: dark ? MUTEDD : MUTED } }],
    { x: W - 1.2, y: 0.34, w: 0.8, h: 0.3, align: "right", fontFace: "Consolas", fontSize: 10, margin: 0 }
  );
}
// small filled accent square — the repeated motif
function marker(slide, x, y, s = 0.1, color = ACCENT) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w: s, h: s, fill: { color }, line: { type: "none" } });
}
function lightHeader(slide, kicker, title, n) {
  slide.background = { color: LIGHT };
  marker(slide, M, 0.46, 0.1);
  slide.addText(kicker, { x: M + 0.2, y: 0.4, w: 7, h: 0.26, fontFace: "Consolas", fontSize: 10.5,
    color: ACCENT, charSpacing: 2, bold: true, margin: 0 });
  slide.addText(title, { x: M, y: 0.72, w: W - 1.6, h: 0.62, fontFace: HEAD, fontSize: 28,
    color: INK, bold: true, margin: 0 });
  pageNum(slide, n, false);
}
// framed screenshot (sharp corners, thin border) preserving aspect by height
function shotByHeight(slide, file, x, y, h, opts = {}) {
  const w = h * SHOT_AR;
  slide.addShape(pres.shapes.RECTANGLE, { x: x - 0.02, y: y - 0.02, w: w + 0.04, h: h + 0.04,
    fill: { color: LIGHT }, line: { color: LINE, width: 1 } });
  slide.addImage({ path: `${SHOTS}/${file}`, x, y, w, h });
  return w;
}
function shotByWidth(slide, file, x, y, w) {
  const h = w / SHOT_AR;
  slide.addShape(pres.shapes.RECTANGLE, { x: x - 0.02, y: y - 0.02, w: w + 0.04, h: h + 0.04,
    fill: { color: LIGHT }, line: { color: LINE, width: 1 } });
  slide.addImage({ path: `${SHOTS}/${file}`, x, y, w, h });
  return h;
}
function dashBox(slide, x, y, w, h, label, dark) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: dark ? INK2 : PANEL },
    line: { color: dark ? "44515A" : LINE, width: 1, dashType: "dash" } });
  slide.addText(label, { x: x + 0.1, y, w: w - 0.2, h, align: "center", valign: "middle",
    fontFace: BODY, italic: true, fontSize: 9.5, color: dark ? MUTEDD : MUTED, margin: 0 });
}

// ════════════════════════════ SLIDE 1 — TITLE ════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: INK };
  marker(s, M, 0.92, 0.12);
  s.addText("PROJECT INCEPTION   ·   2026", { x: M + 0.24, y: 0.86, w: 8, h: 0.28,
    fontFace: "Consolas", fontSize: 11.5, color: MUTEDD, charSpacing: 2, margin: 0 });

  s.addText("RigVision-3D", { x: M, y: 1.55, w: 9, h: 1.0, fontFace: HEAD, fontSize: 58, color: LIGHT, bold: true, margin: 0 });
  s.addText("Real-time 3D Digital Twin for RigVision Drilling Rig Monitoring",
    { x: M, y: 2.62, w: 8.6, h: 0.5, fontFace: BODY, fontSize: 18, color: "C9D0D6", margin: 0 });

  // meta
  s.addText([
    { text: "Team", options: { color: ACCENT, bold: true } },
    { text: "    4 students · LNMIIT, Jaipur — Communication & Computer Engineering", options: { color: MUTEDD } },
  ], { x: M, y: 3.55, w: 9, h: 0.3, fontFace: BODY, fontSize: 12.5, margin: 0 });
  s.addText([
    { text: "Mentor", options: { color: ACCENT, bold: true } },
    { text: "    [ Mentor's name ]", options: { color: MUTEDD } },
  ], { x: M, y: 3.92, w: 9, h: 0.3, fontFace: BODY, fontSize: 12.5, margin: 0 });

  // hairline above branding
  s.addShape(pres.shapes.LINE, { x: M, y: 4.62, w: W - 2 * M, h: 0, line: { color: "3A444C", width: 1 } });
  dashBox(s, M, 4.82, 2.0, 0.55, "RigVision logo", true);
  dashBox(s, M + 2.2, 4.82, 2.0, 0.55, "LNMIIT logo", true);

  s.addNotes("30 seconds — introduce team, set the room for the next 8 minutes.");
}

// ════════════════════════════ SLIDE 2 — WHAT IS IT (full-bleed) ═══════════
{
  const s = pres.addSlide();
  s.background = { color: INK };
  // full-bleed hero
  s.addImage({ path: `${SHOTS}/live-monitor.jpeg`, x: 0, y: 0, w: W, h: H });
  // top scrim for headline legibility
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: 1.9, fill: { color: SCRIM, transparency: 14 }, line: { type: "none" } });
  // bottom scrim for pills
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 4.55, w: W, h: 1.075, fill: { color: SCRIM, transparency: 14 }, line: { type: "none" } });

  marker(s, M, 0.46, 0.1);
  s.addText("WHAT IS RIGVISION-3D", { x: M + 0.2, y: 0.4, w: 8, h: 0.26, fontFace: "Consolas", fontSize: 10.5, color: "E7C9CB", charSpacing: 2, bold: true, margin: 0 });
  s.addText("The rig as a live 3D model — workers, sensors and safety alerts in one place.",
    { x: M, y: 0.74, w: 8.7, h: 0.85, fontFace: HEAD, fontSize: 23, color: LIGHT, bold: true, margin: 0, shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 90, opacity: 0.4 } });
  pageNum(s, 2, true);

  // three pills
  const pills = ["Live person tracking", "PPE compliance", "AI anomaly explainer"];
  let px = M;
  for (const p of pills) {
    const w = 0.34 + p.length * 0.097;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: px, y: 4.82, w, h: 0.42, rectRadius: 0.21,
      fill: { color: INK, transparency: 18 }, line: { color: "FFFFFF", width: 0.75 } });
    s.addText(p, { x: px, y: 4.82, w, h: 0.42, align: "center", valign: "middle", fontFace: BODY, fontSize: 11.5, color: LIGHT, margin: 0 });
    px += w + 0.22;
  }
  s.addNotes("45 seconds — let the screenshot do the talking. Don't read bullets.");
}

// ════════════════════════════ SLIDE 3 — THE PROBLEM ══════════════════════
{
  const s = pres.addSlide();
  lightHeader(s, "THE PROBLEM — WHY WE BUILT THIS", "From Six Screens to One View", 3);

  const colW = 4.35;
  // Left — Today's control room
  s.addText("Today's control room", { x: M, y: 1.55, w: colW, h: 0.36, fontFace: HEAD, fontSize: 16, color: INK, bold: true, margin: 0 });
  const probs = [
    "6+ disconnected screens — CCTV grid, sensor charts, PPE logs, compliance sheets",
    "Operators are reactive — problems are noticed only after they happen",
    "When something goes wrong, no system explains why or what to do",
  ];
  let y = 2.05;
  for (const p of probs) {
    marker(s, M, y + 0.07, 0.09, MUTED);
    s.addText(p, { x: M + 0.26, y, w: colW - 0.26, h: 0.7, fontFace: BODY, fontSize: 12.5, color: TXT, margin: 0, lineSpacingMultiple: 1.0 });
    y += 0.82;
  }

  // divider
  s.addShape(pres.shapes.LINE, { x: 4.98, y: 1.55, w: 0, h: 3.35, line: { color: LINE, width: 1 } });

  // Right — Our goal (panel)
  const rx = 5.25;
  s.addShape(pres.shapes.RECTANGLE, { x: rx, y: 1.55, w: 4.2, h: 3.35, fill: { color: PANEL }, line: { type: "none" } });
  s.addShape(pres.shapes.RECTANGLE, { x: rx, y: 1.55, w: 0.07, h: 3.35, fill: { color: ACCENT }, line: { type: "none" } });
  s.addText("Our goal", { x: rx + 0.28, y: 1.78, w: 3.7, h: 0.36, fontFace: HEAD, fontSize: 16, color: INK, bold: true, margin: 0 });
  const goals = [
    "One single view of the rig",
    "People, sensors and alerts shown in the context of where they physically are",
    "Problems explained in plain language, with clear action steps",
  ];
  y = 2.3;
  for (const g of goals) {
    marker(s, rx + 0.28, y + 0.07, 0.09, ACCENT);
    s.addText(g, { x: rx + 0.54, y, w: 3.55, h: 0.72, fontFace: BODY, fontSize: 12.5, color: TXT, margin: 0, lineSpacingMultiple: 1.0 });
    y += 0.8;
  }
  s.addNotes("60 seconds — frame this as a workflow problem, not a tech problem. Seniors care about operator outcomes.");
}

// ════════════════════════════ SLIDE 4 — FEATURES ═════════════════════════
{
  const s = pres.addSlide();
  lightHeader(s, "FEATURES", "What RigVision-3D Does", 4);

  const rows = [
    ["3D digital twin", "Browser-based rig model with floors, equipment and zones (green / amber / red)"],
    ["Live person tracking", "Four cameras detect workers and place avatars in their real positions"],
    ["PPE detection", "Per-worker check for hard hat, vest and goggles — instant violation flags"],
    ["Sensor monitoring", "Temperature, vibration, noise, gas (H₂S), pressure drive live zone colour"],
    ["AI anomaly explainer", "LLM grounded in equipment manuals explains cause, action and confidence"],
  ];
  const tbl = [[
    { text: "Feature", options: { bold: true, color: LIGHT, fill: { color: INK }, fontSize: 12.5, fontFace: BODY, align: "left", margin: [4, 6, 4, 6], valign: "middle" } },
    { text: "What it does", options: { bold: true, color: LIGHT, fill: { color: INK }, fontSize: 12.5, fontFace: BODY, align: "left", margin: [4, 6, 4, 6], valign: "middle" } },
  ]];
  rows.forEach((r, i) => {
    const fill = i % 2 === 0 ? LIGHT : PANEL;
    tbl.push([
      { text: r[0], options: { bold: true, color: INK, fill: { color: fill }, fontSize: 12, fontFace: BODY, align: "left", margin: [5, 6, 5, 6], valign: "middle" } },
      { text: r[1], options: { color: TXT, fill: { color: fill }, fontSize: 11.5, fontFace: BODY, align: "left", margin: [5, 6, 5, 6], valign: "middle" } },
    ]);
  });
  s.addTable(tbl, { x: M, y: 1.55, w: 6.0, colW: [1.85, 4.15], rowH: 0.62,
    border: { type: "solid", pt: 0.75, color: LINE }, valign: "middle" });

  // two small thumbnails on the right
  shotByWidth(s, "zones-view.jpeg", 6.85, 1.55, 2.6);
  shotByWidth(s, "ppe-proof.jpeg", 6.85, 3.35, 2.6);
  s.addNotes("45 seconds — point at each, move on. Demo will show them live.");
}

// ════════════════════════════ SLIDE 5 — ARCHITECTURE ═════════════════════
{
  const s = pres.addSlide();
  lightHeader(s, "ARCHITECTURE", "Three Pipelines, One Central Server", 5);

  // generic flow-box
  function fbox(x, y, w, h, label) {
    s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: PANEL }, line: { color: "AEB7C0", width: 1 } });
    s.addText(label, { x: x + 0.04, y, w: w - 0.08, h, align: "center", valign: "middle",
      fontFace: BODY, fontSize: 9.5, color: TXT, margin: 0, lineSpacingMultiple: 0.9 });
  }
  function arrow(x, y) {
    s.addShape(pres.shapes.LINE, { x, y, w: 0.18, h: 0, line: { color: MUTED, width: 1.25, endArrowType: "triangle" } });
  }
  // lane label
  function lane(y, tag) {
    s.addText(tag, { x: M, y: y - 0.02, w: 1.35, h: 0.5, fontFace: BODY, bold: true, fontSize: 10.5, color: ACCENT, valign: "middle", margin: 0, lineSpacingMultiple: 0.9 });
  }
  const lx = M + 1.45;            // lane content start
  const bh = 0.5;

  // Lane 1 — Computer Vision
  lane(1.7, "Computer\nVision");
  {
    const items = ["Cameras", "YOLO", "BoT-SORT", "ArUco match", "3D triangulation"];
    const bw = 1.34, gap = 0.2; let x = lx;
    items.forEach((it, i) => { fbox(x, 1.62, bw, bh, it); if (i < items.length - 1) arrow(x + bw + 0.01, 1.62 + bh / 2); x += bw + gap; });
  }
  // Lane 2 — Sensor + AI Diagnostics
  lane(2.55, "Sensor + AI\nDiagnostics");
  {
    const items = ["Sensor\nConsole", "Redis", "Threshold\ncheck", "Kafka", "Graph +\nLLM", "Frontend"];
    const bw = 1.1, gap = 0.146; let x = lx;
    items.forEach((it, i) => { fbox(x, 2.47, bw, bh, it); if (i < items.length - 1) arrow(x + bw + 0.005, 2.47 + bh / 2); x += bw + gap; });
  }
  // Lane 3 — Authentication
  lane(3.4, "Authen-\ntication");
  {
    fbox(lx, 3.32, 1.34, bh, "JWT login");
    arrow(lx + 1.35, 3.32 + bh / 2);
    fbox(lx + 1.54, 3.32, 1.34, bh, "Express");
    arrow(lx + 1.54 + 1.35, 3.32 + bh / 2);
    fbox(lx + 3.08, 3.32, 1.34, bh, "MongoDB");
  }

  // central server note
  s.addShape(pres.shapes.LINE, { x: M, y: 4.15, w: W - 2 * M, h: 0, line: { color: LINE, width: 1 } });
  marker(s, M, 4.42, 0.1);
  s.addText([
    { text: "Redis is the seam.  ", options: { bold: true, color: INK } },
    { text: "Every pipeline reads and writes one shared live store — so any producer can be swapped without touching what's downstream.", options: { color: MUTED } },
  ], { x: M + 0.22, y: 4.34, w: W - 2 * M - 0.22, h: 0.5, fontFace: BODY, fontSize: 11.5, margin: 0, lineSpacingMultiple: 1.0 });
  s.addNotes("90 seconds — walk the diagram. Don't go deep; depth comes in the next slide.");
}

// ════════════════════════════ SLIDE 6 — CHALLENGES ═══════════════════════
{
  const s = pres.addSlide();
  lightHeader(s, "IMPLEMENTATION CHALLENGES", "Problem → What We Tried → What Worked", 6);

  const cards = [
    ["1", "Running everything in parallel",
      "CV detection, sensor ingest and diagnostics can't block each other.",
      "A single in-process orchestrator with Redis as the seam between pipelines."],
    ["2", "Consistent camera setup across devices",
      "Different phone models, each with its own resolution and auto-focus, broke calibration.",
      "Standardised on DroidCam — one fixed-resolution stream — and recorded at the calibration resolution."],
    ["3", "Cross-camera identity matching",
      "BoT-SORT with ReID embeddings was too heavy for four simultaneous streams.",
      "Printed ArUco markers as identity anchors — cross-camera identity without heavy ReID."],
    ["4", "PPE detection accuracy",
      "Fine-tuned YOLO (no rig dataset), CLIP and a VLM pipeline all needed per-case tuning.",
      "A pretrained YOLO model for PPE — acceptable accuracy out of the box, minimal extra cost."],
  ];
  const cw = 4.35, ch = 1.62, gx = 0.22, gy = 0.16, x0 = M, y0 = 1.5;
  cards.forEach((c, i) => {
    const cx = x0 + (i % 2) * (cw + gx);
    const cy = y0 + Math.floor(i / 2) * (ch + gy);
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: PANEL }, line: { color: LINE, width: 1 } });
    // number marker
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: 0.34, h: 0.34, fill: { color: ACCENT }, line: { type: "none" } });
    s.addText(c[0], { x: cx, y: cy, w: 0.34, h: 0.34, align: "center", valign: "middle", fontFace: BODY, bold: true, fontSize: 13, color: LIGHT, margin: 0 });
    s.addText(c[1], { x: cx + 0.46, y: cy + 0.04, w: cw - 0.6, h: 0.34, fontFace: BODY, bold: true, fontSize: 12.5, color: INK, valign: "middle", margin: 0 });
    s.addText([
      { text: "Problem   ", options: { bold: true, color: ACCENT, fontSize: 9.5 } },
      { text: c[2], options: { color: TXT, fontSize: 10.5 } },
    ], { x: cx + 0.16, y: cy + 0.46, w: cw - 0.32, h: 0.52, fontFace: BODY, margin: 0, lineSpacingMultiple: 0.96, valign: "top" });
    s.addText([
      { text: "Worked   ", options: { bold: true, color: ACCENT, fontSize: 9.5 } },
      { text: c[3], options: { color: TXT, fontSize: 10.5 } },
    ], { x: cx + 0.16, y: cy + 1.02, w: cw - 0.32, h: 0.52, fontFace: BODY, margin: 0, lineSpacingMultiple: 0.96, valign: "top" });
  });
  s.addNotes("2 minutes — the most technical slide. Challenges 2 & 3 show engineering judgment (the boring, working solution); Challenge 4 shows we tried the fancier options first and learned why they didn't fit.");
}

// ════════════════════════════ SLIDE 7 — TECH STACK ═══════════════════════
{
  const s = pres.addSlide();
  lightHeader(s, "TECH STACK", "What's Under the Hood", 7);

  const rows = [
    ["Frontend", "React 19, Vite, Three.js, @react-three/fiber, TailwindCSS, Zustand"],
    ["Backend", "FastAPI (Python 3.11), Uvicorn, Pydantic"],
    ["Authentication", "Node.js, Express, MongoDB, JWT"],
    ["Computer Vision", "YOLOv8, BoT-SORT, OpenCV (calibration, ArUco, triangulation), PyTorch + CUDA"],
    ["Data & Messaging", "Redis (live state), Kafka (alerts), PostgreSQL + TimescaleDB (history)"],
    ["Knowledge & LLM", "Neo4j (knowledge graph), ChromaDB (vectors), LM Studio (local LLM), Gemini (embeddings)"],
    ["Infrastructure", "Docker Compose for all services"],
  ];
  const tbl = [[
    { text: "Layer", options: { bold: true, color: LIGHT, fill: { color: INK }, fontSize: 12, fontFace: BODY, align: "left", margin: [4, 6, 4, 6], valign: "middle" } },
    { text: "Technologies", options: { bold: true, color: LIGHT, fill: { color: INK }, fontSize: 12, fontFace: BODY, align: "left", margin: [4, 6, 4, 6], valign: "middle" } },
  ]];
  rows.forEach((r, i) => {
    const fill = i % 2 === 0 ? LIGHT : PANEL;
    tbl.push([
      { text: r[0], options: { bold: true, color: ACCENT, fill: { color: fill }, fontSize: 11.5, fontFace: BODY, align: "left", margin: [5, 6, 5, 6], valign: "middle" } },
      { text: r[1], options: { color: TXT, fill: { color: fill }, fontSize: 11.5, fontFace: BODY, align: "left", margin: [5, 6, 5, 6], valign: "middle" } },
    ]);
  });
  s.addTable(tbl, { x: M, y: 1.55, w: W - 2 * M, colW: [2.2, 6.7], rowH: 0.44,
    border: { type: "solid", pt: 0.75, color: LINE }, valign: "middle" });
  s.addNotes("30 seconds — don't read the list, just say 'here's what's under the hood, ask about any of it in Q&A.'");
}

// ════════════════════════════ SLIDE 8 — DEMO ═════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: INK };
  marker(s, M, 2.05, 0.14);
  s.addText("LIVE", { x: M + 0.28, y: 1.98, w: 3, h: 0.3, fontFace: "Consolas", fontSize: 12, color: MUTEDD, charSpacing: 3, margin: 0 });
  s.addText("Demo", { x: M, y: 2.35, w: 8, h: 1.1, fontFace: HEAD, fontSize: 64, color: LIGHT, bold: true, margin: 0 });
  s.addText("Login  →  3D view  →  trigger an anomaly  →  AI diagnostics",
    { x: M, y: 3.5, w: 9, h: 0.4, fontFace: BODY, fontSize: 16, color: "C9D0D6", margin: 0 });
  pageNum(s, 8, true);
  s.addNotes("3-4 minutes. Path: 1) Sign in  2) Show 3D view, orbit/walk camera  3) Click a tracked person -> camera feeds + PPE panel  4) Open Sensor Console -> push gas value into critical  5) Watch the AI diagnostics modal appear  6) Open Incident Response Hub for the full report.");
}

pres.writeFile({ fileName: "C:/Users/Satvik/Desktop/RigVision/outputs/deck/RigVision-3D_Board_v2.pptx" })
  .then(() => console.log("WROTE RigVision-3D_Board_v2.pptx"))
  .catch(e => { console.error(e); process.exit(1); });
