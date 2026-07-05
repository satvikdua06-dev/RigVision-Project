/* RigVision-3D — Board Presentation (10 slides) */
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa");

// ── Palette: Industrial Digital Twin ──────────────────────────────
const C = {
  ink:    "0B1220",   // deep slate navy (dark slides)
  ink2:   "131D2E",   // panel on dark
  ink3:   "1B2940",   // raised panel on dark
  light:  "FFFFFF",   // content slide bg
  panel:  "F1F4F8",   // card on light
  panel2: "E8EDF4",   // alt card
  line:   "D6DEE9",   // hairline on light
  cyan:   "22D3EE",   // primary accent (techy)
  cobalt: "3B82F6",   // secondary accent
  amber:  "F59E0B",   // safety amber
  red:    "EF4444",   // critical
  green:  "34D399",   // ok
  txtD:   "EAEEF5",   // text on dark
  mutedD: "8FA0B8",   // muted on dark
  txtL:   "16203020".slice(0,6), // 162030 text on light
  mutedL: "5B6B82",   // muted on light
};
C.txtL = "162030";

const HEAD = "Georgia";
const BODY = "Calibri";

// ── Icon rasterizer (cached) ──────────────────────────────────────
const iconCache = {};
async function icon(name, color, size = 256) {
  const key = `${name}_${color}_${size}`;
  if (iconCache[key]) return iconCache[key];
  const Comp = FA[name];
  if (!Comp) throw new Error("missing icon " + name);
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Comp, { color, size: String(size) })
  );
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  const data = "image/png;base64," + png.toString("base64");
  iconCache[key] = data;
  return data;
}

const shadow = () => ({ type: "outer", color: "0B1220", blur: 9, offset: 3, angle: 90, opacity: 0.16 });
const shadowSoft = () => ({ type: "outer", color: "0B1220", blur: 7, offset: 2, angle: 90, opacity: 0.10 });

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10 x 5.625
pres.author = "Team RigVision · LNMIIT";
pres.title = "RigVision-3D";

const W = 10, H = 5.625, M = 0.55;

// ── Reusable bits ─────────────────────────────────────────────────
function pageNum(slide, n, dark) {
  slide.addText(
    [{ text: `${String(n).padStart(2, "0")}`, options: { color: dark ? C.cyan : C.cobalt, bold: true } },
     { text: ` / 10`, options: { color: dark ? C.mutedD : C.mutedL } }],
    { x: W - 1.5, y: H - 0.42, w: 1.1, h: 0.3, align: "right", fontFace: "Consolas", fontSize: 9, margin: 0 }
  );
}
function footer(slide, dark) {
  slide.addText("RIGVISION-3D", { x: M, y: H - 0.42, w: 3, h: 0.3, fontFace: "Consolas",
    fontSize: 8, color: dark ? C.mutedD : C.mutedL, charSpacing: 2, margin: 0 });
}
// eyebrow + title block on light slides
function lightHeader(slide, kicker, title, n) {
  slide.background = { color: C.light };
  slide.addText(kicker, { x: M, y: 0.42, w: 8, h: 0.3, fontFace: "Consolas", fontSize: 10.5,
    color: C.cyan, charSpacing: 3, bold: true, margin: 0 });
  slide.addText(title, { x: M, y: 0.72, w: W - 2 * M, h: 0.7, fontFace: HEAD, fontSize: 30,
    color: C.txtL, bold: true, margin: 0 });
  pageNum(slide, n, false);
  footer(slide, false);
}
// dashed image placeholder
async function placeholder(slide, x, y, w, h, caption, dark) {
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h,
    fill: { color: dark ? C.ink2 : C.panel },
    line: { color: dark ? C.ink3 : C.line, width: 1.25, dashType: "dash" } });
  const ic = await icon("FaRegImage", dark ? C.mutedD : "9AA9BD", 200);
  slide.addImage({ data: ic, x: x + w / 2 - 0.22, y: y + h / 2 - 0.42, w: 0.44, h: 0.44 });
  slide.addText(caption, { x: x + 0.18, y: y + h / 2 + 0.04, w: w - 0.36, h: h / 2 - 0.18,
    align: "center", valign: "top", fontFace: BODY, italic: true, fontSize: 10,
    color: dark ? C.mutedD : C.mutedL, margin: 0 });
}
async function iconCircle(slide, x, y, d, name, ringColor, glyphColor) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: ringColor } });
  const ic = await icon(name, glyphColor || "FFFFFF", 220);
  const ip = d * 0.5;
  slide.addImage({ data: ic, x: x + (d - ip) / 2, y: y + (d - ip) / 2, w: ip, h: ip });
}

async function build() {
  // ════════════════════════════ SLIDE 1 — TITLE ════════════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    // ambient glow accents
    s.addShape(pres.shapes.OVAL, { x: -1.6, y: -1.8, w: 4.2, h: 4.2, fill: { color: C.cobalt, transparency: 88 }, line: { type: "none" } });
    s.addShape(pres.shapes.OVAL, { x: 6.3, y: 3.0, w: 4.6, h: 4.6, fill: { color: C.cyan, transparency: 90 }, line: { type: "none" } });

    s.addText("RigVision  ×  LNMIIT   ·   DIGITAL TWIN INITIATIVE", { x: M, y: 0.6, w: 8.5, h: 0.3,
      fontFace: "Consolas", fontSize: 11, color: C.cyan, charSpacing: 3, bold: true, margin: 0 });

    s.addText("RigVision-3D", { x: M, y: 1.5, w: 8, h: 1.1, fontFace: HEAD, fontSize: 60,
      color: C.txtD, bold: true, margin: 0 });
    s.addText("A real-time 3D digital twin for drilling-rig safety & monitoring",
      { x: M, y: 2.62, w: 6.0, h: 0.6, fontFace: BODY, fontSize: 17, color: C.mutedD, margin: 0 });

    // stat chips
    const chips = [
      ["1", "Unified 3D twin"],
      ["4", "Vision cameras"],
      ["5", "Capability pillars"],
    ];
    let cx = M;
    for (const [big, lbl] of chips) {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: cx, y: 3.55, w: 2.0, h: 0.92, rectRadius: 0.08,
        fill: { color: C.ink2 }, line: { color: C.ink3, width: 1 } });
      s.addText([
        { text: big + "  ", options: { color: C.cyan, bold: true, fontSize: 24, fontFace: HEAD } },
        { text: lbl, options: { color: C.txtD, fontSize: 11, fontFace: BODY } },
      ], { x: cx + 0.18, y: 3.55, w: 1.7, h: 0.92, valign: "middle", margin: 0 });
      cx += 2.18;
    }

    s.addText([
      { text: "Team RigVision", options: { color: C.txtD, bold: true } },
      { text: "   ·   Core Engineering Team   ·   Initial Development Phase", options: { color: C.mutedD } },
    ], { x: M, y: 4.95, w: 9, h: 0.3, fontFace: BODY, fontSize: 11.5, margin: 0 });

    await placeholder(s, 6.9, 1.45, 2.6, 2.0, "Hero shot: the 3D dashboard with rig model, zones & avatars", true);
    pageNum(s, 1, true);
  }

  // ════════════════════════════ SLIDE 2 — THE CHALLENGE ════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "CONTEXT", "The Challenge on the Rig Floor", 2);
    s.addText("Drilling rigs are high-risk environments — yet today they are watched through fragmented, disconnected screens.",
      { x: M, y: 1.45, w: 5.6, h: 0.8, fontFace: BODY, fontSize: 14.5, color: C.mutedL, margin: 0 });

    const pains = [
      ["FaThLarge", C.cobalt, "Fragmented monitoring", "Camera feeds and sensor panels live on separate screens. Operators stitch the picture together in their heads."],
      ["FaMapMarkerAlt", C.amber, "No spatial awareness", "Where is each worker relative to a gas leak or hot equipment? Flat video can't answer that."],
      ["FaExclamationTriangle", C.red, "Reactive, not proactive", "Alarms sound, but offer no cause and no guidance — response is slow and manual."],
    ];
    let y = 2.35;
    for (const [ic, col, h, b] of pains) {
      s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 5.6, h: 0.92, fill: { color: C.panel }, line: { type: "none" }, shadow: shadowSoft() });
      s.addShape(pres.shapes.RECTANGLE, { x: M, y, w: 0.07, h: 0.92, fill: { color: col }, line: { type: "none" } });
      await iconCircle(s, M + 0.22, y + 0.22, 0.48, ic, col);
      s.addText([
        { text: h + "\n", options: { bold: true, fontSize: 13.5, color: C.txtL, fontFace: BODY } },
        { text: b, options: { fontSize: 10.5, color: C.mutedL, fontFace: BODY } },
      ], { x: M + 0.86, y: y + 0.1, w: 4.6, h: 0.74, valign: "middle", margin: 0, lineSpacingMultiple: 1.0 });
      y += 1.04;
    }
    await placeholder(s, 6.45, 1.45, 3.0, 3.55, "Photo: a rig control room with a wall of separate camera & sensor monitors", false);
  }

  // ════════════════════════════ SLIDE 3 — OBJECTIVES ═══════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "GOALS", "What We Set Out to Achieve", 3);

    const objs = [
      ["FaCube", C.cobalt, "Unify into one 3D view", "Fuse live video and sensor data onto a single interactive digital twin of the rig."],
      ["FaMapMarkedAlt", C.cyan, "Locate people in real time", "Track every person and place them accurately in 3D space, room by room."],
      ["FaHardHat", C.amber, "Automate safety compliance", "Continuously verify protective equipment and occupancy without manual auditing."],
      ["FaBrain", C.green, "Explain, don't just alarm", "Turn a raw threshold breach into a grounded root-cause diagnosis and an action plan."],
      ["FaPlug", C.cobalt, "Build it to be swappable", "A clean data 'seam' so sensors, cameras or models can be replaced without rewrites."],
    ];
    // two-column rows
    const colX = [M, 5.15];
    const colW = 4.35;
    for (let i = 0; i < objs.length; i++) {
      const [ic, col, h, b] = objs[i];
      const x = colX[i % 2];
      const row = Math.floor(i / 2);
      const y = 1.55 + row * 1.18;
      await iconCircle(s, x, y, 0.6, ic, col);
      s.addText([
        { text: h + "\n", options: { bold: true, fontSize: 14, color: C.txtL, fontFace: BODY } },
        { text: b, options: { fontSize: 10.5, color: C.mutedL, fontFace: BODY } },
      ], { x: x + 0.78, y: y - 0.04, w: colW - 0.78, h: 1.05, valign: "top", margin: 0, lineSpacingMultiple: 1.02 });
    }
    // 5th spans nicely already (index 4 -> col 0 row 2). leave the empty slot with a quiet note
    s.addText("Outcome: one screen that shows what is happening, where, and what to do about it.",
      { x: 5.15, y: 4.5, w: 4.35, h: 0.9, fontFace: BODY, italic: true, fontSize: 12.5,
        color: C.cobalt, valign: "middle", margin: 0 });
  }

  // ════════════════════════════ SLIDE 4 — WHAT WE BUILT ════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "SOLUTION", "What We Built — Five Pillars", 4);

    const cards = [
      ["FaCube", C.cobalt, "3D Digital Twin", "Browser-based interactive model. Zones glow green / amber / red by live status; equipment is clickable."],
      ["FaVideo", C.cyan, "Multi-Camera Vision", "Overlapping cameras detect & track people, then triangulate them into real 3D room coordinates."],
      ["FaWaveSquare", C.amber, "Sensor Ingestion", "Temperature, gas, vibration, noise & pressure flow through one swappable data 'seam'."],
      ["FaHardHat", C.green, "Personnel & PPE Safety", "Per-person protective-gear checks across feeds, with snapshot proof of any violation."],
      ["FaProjectDiagram", C.cobalt, "AI Diagnostics + Graph", "A knowledge graph plus a trained language model turn breaches into root-cause reports."],
    ];
    // 3 + 2 grid
    const cw = 2.94, ch = 1.62, gap = 0.22;
    const startX = M, startY = 1.55;
    for (let i = 0; i < cards.length; i++) {
      const [ic, col, h, b] = cards[i];
      const row = Math.floor(i / 3), c = i % 3;
      // center the 2 cards on the bottom row
      const rowCount = row === 0 ? 3 : 2;
      const rowW = rowCount * cw + (rowCount - 1) * gap;
      const offX = (W - 2 * M - rowW) / 2;
      const x = startX + offX + c * (cw + gap);
      const y = startY + row * (ch + gap);
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 1 }, shadow: shadowSoft() });
      await iconCircle(s, x + 0.2, y + 0.2, 0.52, ic, col);
      s.addText(`0${i + 1}`, { x: x + cw - 0.7, y: y + 0.16, w: 0.55, h: 0.3, align: "right",
        fontFace: "Consolas", fontSize: 11, color: C.line, bold: true, margin: 0 });
      s.addText(h, { x: x + 0.2, y: y + 0.78, w: cw - 0.4, h: 0.3, fontFace: BODY, bold: true, fontSize: 13, color: C.txtL, margin: 0 });
      s.addText(b, { x: x + 0.2, y: y + 1.06, w: cw - 0.4, h: 0.5, fontFace: BODY, fontSize: 9.5, color: C.mutedL, margin: 0, lineSpacingMultiple: 0.98 });
    }
  }

  // ════════════════════════════ SLIDE 5 — HOW IT WORKS ═════════════════════
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    s.addText("ARCHITECTURE", { x: M, y: 0.42, w: 8, h: 0.3, fontFace: "Consolas", fontSize: 10.5, color: C.cyan, charSpacing: 3, bold: true, margin: 0 });
    s.addText("How It Works — From Cameras to Cognition", { x: M, y: 0.72, w: W - 2 * M, h: 0.6, fontFace: HEAD, fontSize: 28, color: C.txtD, bold: true, margin: 0 });
    pageNum(s, 5, true); footer(s, true);

    const steps = [
      ["FaVideo", C.cyan, "Capture", "Cameras + sensors\nstream the rig floor"],
      ["FaMicrochip", C.cobalt, "Vision Pipeline", "Detect · track ·\ntriangulate in 3D"],
      ["FaDatabase", C.amber, "The Seam", "One shared store\ndecouples everything"],
      ["FaDesktop", C.green, "3D Dashboard", "Live twin: people,\nzones & equipment"],
      ["FaBrain", C.red, "AI Diagnostics", "Grounded root-cause\nreports on demand"],
    ];
    const n = steps.length, cw = 1.56, gap = (W - 2 * M - n * cw) / (n - 1);
    const y = 2.0;
    for (let i = 0; i < n; i++) {
      const [ic, col, h, b] = steps[i];
      const x = M + i * (cw + gap);
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cw, h: 2.1, rectRadius: 0.08, fill: { color: C.ink2 }, line: { color: C.ink3, width: 1 } });
      await iconCircle(s, x + cw / 2 - 0.32, y + 0.24, 0.64, ic, col);
      s.addText(h, { x: x + 0.06, y: y + 1.0, w: cw - 0.12, h: 0.35, align: "center", fontFace: BODY, bold: true, fontSize: 12.5, color: C.txtD, margin: 0 });
      s.addText(b, { x: x + 0.06, y: y + 1.34, w: cw - 0.12, h: 0.7, align: "center", fontFace: BODY, fontSize: 9.5, color: C.mutedD, margin: 0, lineSpacingMultiple: 0.95 });
      if (i < n - 1) {
        const ax = x + cw + gap / 2 - 0.11;
        const ar = await icon("FaChevronRight", C.cyan, 120);
        s.addImage({ data: ar, x: ax, y: y + 0.86, w: 0.22, h: 0.22 });
      }
    }
    s.addText([
      { text: "Why a shared 'seam'?  ", options: { bold: true, color: C.cyan } },
      { text: "Each stage writes to one common store — so a manual sensor today can become a live field sensor tomorrow with zero changes downstream.", options: { color: C.mutedD } },
    ], { x: M, y: 4.45, w: W - 2 * M, h: 0.6, fontFace: BODY, fontSize: 12, align: "center", margin: 0 });
  }

  // ════════════════════════════ SLIDE 6 — TWIN + VISION ════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "CAPABILITY · 1", "The Digital Twin & Live Vision", 6);

    // Left column — Digital Twin
    const colW = 4.35;
    await iconCircle(s, M, 1.5, 0.56, "FaCube", C.cobalt);
    s.addText("3D Digital Twin", { x: M + 0.72, y: 1.5, w: colW - 0.72, h: 0.4, fontFace: BODY, bold: true, fontSize: 16, color: C.txtL, valign: "middle", margin: 0 });
    s.addText([
      { text: "What:  ", options: { bold: true, color: C.cobalt } },
      { text: "An interactive browser model of the rig. Zones change colour with live status; equipment is clickable for detail.", options: { color: C.mutedL } },
    ], { x: M, y: 2.15, w: colW, h: 0.95, fontFace: BODY, fontSize: 11.5, margin: 0, lineSpacingMultiple: 1.02 });
    s.addText([
      { text: "Why:  ", options: { bold: true, color: C.cobalt } },
      { text: "Spatial context beats a grid of flat feeds — operators instantly see who is where, near what hazard.", options: { color: C.mutedL } },
    ], { x: M, y: 3.05, w: colW, h: 0.8, fontFace: BODY, fontSize: 11.5, margin: 0, lineSpacingMultiple: 1.02 });
    await placeholder(s, M, 3.9, colW, 1.15, "Screenshot: 3D rig model with coloured zones", false);

    // divider
    s.addShape(pres.shapes.LINE, { x: 4.95, y: 1.5, w: 0, h: 3.55, line: { color: C.line, width: 1 } });

    // Right column — Vision
    const rx = 5.25;
    await iconCircle(s, rx, 1.5, 0.56, "FaVideo", C.cyan);
    s.addText("Multi-Camera Vision", { x: rx + 0.72, y: 1.5, w: colW - 0.72, h: 0.4, fontFace: BODY, bold: true, fontSize: 16, color: C.txtL, valign: "middle", margin: 0 });
    s.addText([
      { text: "What:  ", options: { bold: true, color: C.cyan } },
      { text: "Two overlapping cameras per room detect and track people, then triangulate them into true 3D room coordinates.", options: { color: C.mutedL } },
    ], { x: rx, y: 2.15, w: colW, h: 0.95, fontFace: BODY, fontSize: 11.5, margin: 0, lineSpacingMultiple: 1.02 });
    s.addText([
      { text: "Why:  ", options: { bold: true, color: C.cyan } },
      { text: "Fusing each room independently keeps rooms from contaminating each other and avoids a fragile single world map.", options: { color: C.mutedL } },
    ], { x: rx, y: 3.05, w: colW, h: 0.8, fontFace: BODY, fontSize: 11.5, margin: 0, lineSpacingMultiple: 1.02 });
    await placeholder(s, rx, 3.9, colW, 1.15, "Screenshot: camera feeds with tracked people boxed", false);
  }

  // ════════════════════════════ SLIDE 7 — PPE / SAFETY ═════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "CAPABILITY · 2", "Personnel Safety & PPE Compliance", 7);

    s.addText([
      { text: "A trained model checks each tracked worker for required protective gear — across every camera that can see them — and flags anyone non-compliant, per person.", options: { color: C.mutedL } },
    ], { x: M, y: 1.5, w: 5.5, h: 1.0, fontFace: BODY, fontSize: 14, margin: 0, lineSpacingMultiple: 1.05 });

    const pts = [
      ["FaUserCheck", C.cobalt, "Per-person, not per-frame", "Each worker carries their own compliance status, not a single yes/no for the whole scene."],
      ["FaVideo", C.cyan, "Multi-camera confidence", "If any feed sees the gear on a person, they count as compliant — fewer false flags."],
      ["FaCamera", C.amber, "Proof on every flag", "A snapshot is captured the moment a violation is detected, for audit and review."],
    ];
    let y = 2.45;
    for (const [ic, col, h, b] of pts) {
      await iconCircle(s, M, y, 0.52, ic, col);
      s.addText([
        { text: h + "\n", options: { bold: true, fontSize: 13, color: C.txtL, fontFace: BODY } },
        { text: b, options: { fontSize: 10.5, color: C.mutedL, fontFace: BODY } },
      ], { x: M + 0.7, y: y - 0.04, w: 4.85, h: 0.78, margin: 0, lineSpacingMultiple: 1.0 });
      y += 0.8;
    }
    s.addText([
      { text: "Why it matters:  ", options: { bold: true, color: C.amber } },
      { text: "manual PPE auditing can't scale to a busy rig — automated, per-person checking makes safety continuous.", options: { color: C.mutedL } },
    ], { x: M, y: 4.82, w: 5.5, h: 0.45, fontFace: BODY, italic: true, fontSize: 11, margin: 0 });

    await placeholder(s, 6.45, 1.5, 3.0, 3.5, "Screenshot: person cards showing per-worker PPE status + a proof snapshot", false);
  }

  // ════════════════════════════ SLIDE 8 — AI DIAGNOSTICS ═══════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "CAPABILITY · 3", "From Alarms to Answers", 8);

    s.addText("When a reading crosses a real, manual-derived safety limit, the system doesn't just beep — it investigates.",
      { x: M, y: 1.5, w: 5.6, h: 0.7, fontFace: BODY, fontSize: 14, color: C.mutedL, margin: 0, lineSpacingMultiple: 1.05 });

    const steps = [
      ["FaExclamationTriangle", C.red, "Breach detected", "A sensor crosses a limit drawn from the equipment's own manuals."],
      ["FaProjectDiagram", C.cobalt, "Graph lookup", "A knowledge graph links the zone to its equipment and known failure modes."],
      ["FaBookOpen", C.cyan, "Manual context", "Relevant manual passages are retrieved to ground the analysis in fact."],
      ["FaBrain", C.green, "Root-cause report", "A trained model writes the likely cause, confidence and recommended actions."],
    ];
    let y = 2.3;
    for (let i = 0; i < steps.length; i++) {
      const [ic, col, h, b] = steps[i];
      await iconCircle(s, M, y, 0.5, ic, col);
      if (i < steps.length - 1) s.addShape(pres.shapes.LINE, { x: M + 0.25, y: y + 0.5, w: 0, h: 0.18, line: { color: C.line, width: 1.5 } });
      s.addText([
        { text: h + "   ", options: { bold: true, fontSize: 12.5, color: C.txtL, fontFace: BODY } },
        { text: b, options: { fontSize: 10.5, color: C.mutedL, fontFace: BODY } },
      ], { x: M + 0.68, y: y + 0.02, w: 4.95, h: 0.62, valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
      y += 0.68;
    }

    // why on-demand callout
    s.addShape(pres.shapes.RECTANGLE, { x: 6.45, y: 1.5, w: 3.0, h: 3.5, fill: { color: C.ink }, line: { type: "none" }, shadow: shadow() });
    s.addText("WHY ON-DEMAND?", { x: 6.65, y: 1.72, w: 2.6, h: 0.3, fontFace: "Consolas", fontSize: 10, color: C.cyan, charSpacing: 2, bold: true, margin: 0 });
    s.addText([
      { text: "No false alarms.\n", options: { bold: true, color: C.txtD, breakLine: true } },
      { text: "The model runs only when data truly breaches a limit — never inventing problems.\n\n", options: { color: C.mutedD, breakLine: true } },
      { text: "Always grounded.\n", options: { bold: true, color: C.txtD, breakLine: true } },
      { text: "Answers are anchored to real device manuals, not guesswork.", options: { color: C.mutedD } },
    ], { x: 6.65, y: 2.12, w: 2.62, h: 2.7, fontFace: BODY, fontSize: 11, margin: 0, lineSpacingMultiple: 1.05, valign: "top" });
  }

  // ════════════════════════════ SLIDE 9 — TECH STACK ═══════════════════════
  {
    const s = pres.addSlide();
    lightHeader(s, "ENGINEERING", "Technology Stack", 9);

    const groups = [
      ["FaCube", C.cobalt, "3D & Frontend", ["Three.js + React", "Zustand state", "Vite build"]],
      ["FaEye", C.cyan, "Computer Vision", ["Trained detection model", "Multi-object tracking", "OpenCV / camera calibration"]],
      ["FaServer", C.amber, "Backend & Data", ["FastAPI services", "Redis · the live seam", "PostgreSQL + TimescaleDB", "Kafka alert bus"]],
      ["FaBrain", C.green, "Intelligence", ["Neo4j knowledge graph", "Vector search (RAG)", "Local language model"]],
    ];
    const cw = 2.18, gap = 0.18, y = 1.55, ch = 3.05;
    for (let i = 0; i < groups.length; i++) {
      const [ic, col, h, items] = groups[i];
      const x = M + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 1 }, shadow: shadowSoft() });
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: 0.07, fill: { color: col }, line: { type: "none" } });
      await iconCircle(s, x + 0.2, y + 0.26, 0.5, ic, col);
      s.addText(h, { x: x + 0.18, y: y + 0.85, w: cw - 0.36, h: 0.35, fontFace: BODY, bold: true, fontSize: 12.5, color: C.txtL, margin: 0 });
      s.addText(items.map((t, k) => ({ text: t, options: { bullet: { code: "2022", indent: 12 }, breakLine: true, fontSize: 10.5, color: C.mutedL, fontFace: BODY, paraSpaceAfter: 6 } })),
        { x: x + 0.2, y: y + 1.25, w: cw - 0.38, h: ch - 1.4, margin: 0 });
    }
    s.addText([
      { text: "Hardware:  ", options: { bold: true, color: C.cobalt } },
      { text: "a single RTX 4070 workstation drives the full vision + AI pipeline alongside networked cameras.", options: { color: C.mutedL } },
    ], { x: M, y: 4.78, w: W - 2 * M, h: 0.4, fontFace: BODY, fontSize: 11.5, align: "center", margin: 0 });
  }

  // ════════════════════════════ SLIDE 10 — CHALLENGES + ROADMAP ════════════
  {
    const s = pres.addSlide();
    s.background = { color: C.ink };
    s.addShape(pres.shapes.OVAL, { x: 6.6, y: -1.7, w: 4.4, h: 4.4, fill: { color: C.cobalt, transparency: 90 }, line: { type: "none" } });
    s.addText("REFLECTION", { x: M, y: 0.42, w: 8, h: 0.3, fontFace: "Consolas", fontSize: 10.5, color: C.cyan, charSpacing: 3, bold: true, margin: 0 });
    s.addText("Challenges We Solved & The Road Ahead", { x: M, y: 0.72, w: W - 2 * M, h: 0.6, fontFace: HEAD, fontSize: 27, color: C.txtD, bold: true, margin: 0 });
    pageNum(s, 10, true); footer(s, true);

    // Challenges column
    await iconCircle(s, M, 1.6, 0.5, "FaTools", C.amber);
    s.addText("Challenges We Faced", { x: M + 0.66, y: 1.6, w: 4, h: 0.45, fontFace: BODY, bold: true, fontSize: 15, color: C.txtD, valign: "middle", margin: 0 });
    const ch = [
      "Locating people in 3D from low-cost cameras at oblique angles & distance",
      "Reliable detection when a worker is far from the lens",
      "Keeping the AI honest — grounded answers, never false alarms",
      "Designing a sensor 'seam' that swaps producers without downstream rewrites",
    ];
    s.addText(ch.map(t => ({ text: t, options: { bullet: { code: "2022", indent: 14 }, breakLine: true, fontSize: 11.5, color: C.mutedD, fontFace: BODY, paraSpaceAfter: 10 } })),
      { x: M, y: 2.25, w: 4.35, h: 2.5, margin: 0, lineSpacingMultiple: 1.0 });

    // divider
    s.addShape(pres.shapes.LINE, { x: 4.95, y: 1.6, w: 0, h: 3.0, line: { color: C.ink3, width: 1 } });

    // Roadmap column
    const rx = 5.25;
    await iconCircle(s, rx, 1.6, 0.5, "FaRoute", C.green);
    s.addText("The Road Ahead", { x: rx + 0.66, y: 1.6, w: 4, h: 0.45, fontFace: BODY, bold: true, fontSize: 15, color: C.txtD, valign: "middle", margin: 0 });
    const rd = [
      "Live field-sensor bridge feeding the same seam",
      "Automated PPE violations folded into zone status",
      "Full stereo coverage + survey-grade camera calibration",
      "Pilot deployment on an operational industrial rig",
    ];
    s.addText(rd.map(t => ({ text: t, options: { bullet: { code: "2022", indent: 14 }, breakLine: true, fontSize: 11.5, color: C.mutedD, fontFace: BODY, paraSpaceAfter: 10 } })),
      { x: rx, y: 2.25, w: 4.35, h: 2.5, margin: 0, lineSpacingMultiple: 1.0 });

    s.addText("Thank you  ·  Team RigVision  ·  LNMIIT × RigVision", { x: M, y: 5.0, w: W - 2 * M, h: 0.35, align: "center", fontFace: BODY, fontSize: 12, color: C.cyan, bold: true, margin: 0 });
  }

  await pres.writeFile({ fileName: "C:/Users/Satvik/Desktop/RigVision/outputs/deck/RigVision-3D_Board.pptx" });
  console.log("WROTE RigVision-3D_Board.pptx");
}

build().catch(e => { console.error(e); process.exit(1); });
