#!/usr/bin/env bun
// diagram_poster.ts — render a mermaid diagram (plus an editorial shell) to a
// pastel PNG, so a GitHub wiki/repo shows a clean pre-rendered image instead of
// relying on GitHub's (intermittently failing) mermaid renderer.
//
// Usage: bun tools/diagram_poster.ts input.yaml [-o out.html] [--png]
// Single self-contained file (fixed pastel theme, embedded icons, Bun.YAML).
// Optional tool — NOT part of repodocs' zero-dependency Python core; needs Bun
// and (for --png) playwright/chromium. See README "Optional: diagram posters".
//
// YAML blocks (fixed render order): kicker, headline, sub, mermaid,
// panel{title, blocks:[{tree}|{dashrow}|{checks}]}, tree, dashrow, checks,
// legend, note, band, footer. Inline: [hl] yellow · [hlg] green · [hlb] blue ·
// [hls] salmon · [m] mono · **bold**. Inside band, [hl] becomes yellow text.

import { resolve } from "node:path";

// --- tema (design "team of five", único) -----------------------------------

const T = {
	cream: "#FBF6EA",
	ink: "#2B2B2B",
	stroke: "#3A3A3A",
	charcoal: "#2B2B2B",
	accent: "#C24C32",
	muted: "#6F665D",
	footMuted: "#8A8378",
	line: "#E4DAC6",
	card: "#FFFFFF",
	sans: "'Nunito',-apple-system,'Segoe UI',sans-serif",
	mono: "'Geist Mono',ui-monospace,monospace",
	hand: "'Caveat',cursive",
	fontImport:
		"@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=Geist+Mono:wght@400;500&family=Caveat:wght@500;600&display=swap');",
};

// Gramática semântica: uma cor = um papel (ver SKILL.md).
type ChipColor = "salmon" | "yellow" | "green" | "blue" | "purple" | "paper";
const CHIP: Record<ChipColor, { fill: string; stroke: string; text: string }> =
	{
		salmon: { fill: "#FADCD0", stroke: "#E2795B", text: "#7A2E17" },
		yellow: { fill: "#FAE9B6", stroke: "#D9A93F", text: "#6B5310" },
		green: { fill: "#D4ECCF", stroke: "#6FA860", text: "#2F5626" },
		blue: { fill: "#C9DDF2", stroke: "#5B87BC", text: "#1E3A5C" },
		purple: { fill: "#DFD6F1", stroke: "#8F7CC4", text: "#3D2D66" },
		paper: { fill: "#FFFFFF", stroke: "#3A3A3A", text: "#2B2B2B" },
	};
const COLOR_ALIAS: Record<string, ChipColor> = { red: "salmon" };
function chipOf(c?: string): { fill: string; stroke: string; text: string } {
	const key = (c && (COLOR_ALIAS[c] ?? c)) as ChipColor;
	return CHIP[key] ?? CHIP.blue;
}

// --- ícones outline embutidos (viewBox 0 0 24 24, stroke currentColor) ------

const ICONS: Record<string, string> = {
	person: `<circle cx="12" cy="8" r="3.4" stroke="currentColor" fill="none" stroke-width="1.8"/><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/>`,
	shield: `<path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6l7-3z" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>`,
	doc: `<path d="M6 3h8l4 4v14H6z" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linejoin="round"/><path d="M14 3v4h4" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 13h6M9 17h6" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/>`,
	funnel: `<path d="M4 4h16l-6 8v6l-4 2v-8L4 4z" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>`,
	gear: `<circle cx="12" cy="12" r="3.2" stroke="currentColor" fill="none" stroke-width="1.8"/><path d="M12 3v2.4M12 18.6V21M21 12h-2.4M5.4 12H3M18.1 5.9l-1.7 1.7M7.6 16.4l-1.7 1.7M18.1 18.1l-1.7-1.7M7.6 7.6L5.9 5.9" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/>`,
	calc: `<rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linejoin="round"/><path d="M7.5 6h9" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/><path d="M8 11h0M12 11h0M16 11h0M8 15h0M12 15h0M16 15h0M8 18h0M12 18h0" stroke="currentColor" fill="none" stroke-width="2.6" stroke-linecap="round"/>`,
	chart: `<path d="M4 20V10M9 20V6M14 20v-8M19 20V4" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/><path d="M4 20h15" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round"/>`,
	code: `<path d="M9 7L4 12l5 5M15 7l5 5-5 5" stroke="currentColor" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
};

// --- tipos -------------------------------------------------------------------

type TreeNode = {
	id: string;
	label: string;
	name?: string; // pill de nome no topo do chip (folhas)
	icon?: string;
	color?: string; // folhas: cor do chip (gramática semântica)
	tone?: string; // caixas: tint suave + borda colorida
	parent?: string;
	w?: number;
};
type TreeBlock = { nodes: TreeNode[] };
type DashRow = { text: string };
type CheckItem = { ok: boolean; text: string };
type NoteBlock = { text: string; arrow?: "left" | "right" | "down" };
type PanelSubBlock = { tree?: TreeBlock; dashrow?: DashRow; checks?: CheckItem[] };
type Panel = { title?: string; blocks: PanelSubBlock[] };
type LegendItem = { color: string; label: string };

type Doc = {
	title?: string;
	kicker?: string;
	headline?: string;
	sub?: string;
	mermaid?: string;
	panel?: Panel;
	tree?: TreeBlock;
	dashrow?: DashRow;
	checks?: CheckItem[];
	legend?: LegendItem[];
	note?: NoteBlock;
	band?: string;
	footer?: { left?: string; right?: string };
};

// --- texto -------------------------------------------------------------------

function esc(s: string): string {
	return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function rich(s: string): string {
	return esc(s)
		.replace(/\[hl\](.*?)\[\/hl\]/g, '<span class="hl">$1</span>')
		.replace(/\[hlg\](.*?)\[\/hlg\]/g, '<span class="hlg">$1</span>')
		.replace(/\[hlb\](.*?)\[\/hlb\]/g, '<span class="hlb">$1</span>')
		.replace(/\[hls\](.*?)\[\/hls\]/g, '<span class="hls">$1</span>')
		.replace(/\[m\](.*?)\[\/m\]/g, '<span class="mono">$1</span>')
		.replace(/\*\*(.*?)\*\*/g, "<b>$1</b>");
}

function plainLen(label: string): number {
	return label.replace(/\[\/?\w+\]/g, "").replace(/\*\*/g, "").length;
}

let uidCounter = 0;
function nextId(prefix: string): string {
	uidCounter += 1;
	return `${prefix}${uidCounter}`;
}

// --- tree (org-chart auto-layout) ---------------------------------------------

const TREE_W = 1100;
const LEAF_W = 132;
const LEAF_H = 140;
const BOX_W = 220;
const BOX_H = 64;

type LayoutNode = {
	node: TreeNode;
	x: number;
	y: number;
	w: number;
	h: number;
	isLeaf: boolean;
	depth: number;
};

function childMap(nodes: TreeNode[]): Map<string, TreeNode[]> {
	const ids = new Set(nodes.map((n) => n.id));
	const map = new Map<string, TreeNode[]>();
	for (const n of nodes) {
		if (!n.parent || !ids.has(n.parent)) continue;
		const arr = map.get(n.parent) ?? [];
		arr.push(n);
		map.set(n.parent, arr);
	}
	return map;
}

function depthMap(nodes: TreeNode[]): Map<string, number> {
	const byId = new Map(nodes.map((n) => [n.id, n]));
	const depths = new Map<string, number>();
	function depthOf(id: string): number {
		const cached = depths.get(id);
		if (cached !== undefined) return cached;
		const n = byId.get(id);
		const hasParent = n?.parent && byId.has(n.parent);
		const d = hasParent ? depthOf(n.parent as string) + 1 : 0;
		depths.set(id, d);
		return d;
	}
	for (const n of nodes) depthOf(n.id);
	return depths;
}

function layoutTree(nodes: TreeNode[]): {
	layout: LayoutNode[];
	width: number;
	height: number;
} {
	const depths = depthMap(nodes);
	const children = childMap(nodes);
	const maxDepth = Math.max(...nodes.map((n) => depths.get(n.id) ?? 0));
	const rows: TreeNode[][] = Array.from({ length: maxDepth + 1 }, () => []);
	for (const n of nodes) (rows[depths.get(n.id) ?? 0] as TreeNode[]).push(n);
	// Altura cumulativa por linha (caixas 64, chips 140) — pôster compacto.
	const GAP_Y = 68;
	const rowHeights = rows.map((row) =>
		Math.max(...row.map((n) => (children.get(n.id)?.length ? BOX_H : LEAF_H))),
	);
	const rowY: number[] = [];
	let y = 0;
	for (const h of rowHeights) {
		rowY.push(y);
		y += h + GAP_Y;
	}
	const layout = rows.flatMap((row, depth) => {
		const slot = TREE_W / row.length;
		return row.map((n, i) => {
			const isLeaf = !children.get(n.id)?.length;
			const autoBoxW = Math.min(
				TREE_W,
				Math.max(BOX_W, plainLen(n.label) * 8.6 + (n.icon ? 64 : 24)),
			);
			const w = n.w ?? (isLeaf ? LEAF_W : autoBoxW);
			const h = isLeaf ? LEAF_H : BOX_H;
			const cx = slot * i + slot / 2;
			return {
				node: n,
				x: cx - w / 2,
				y: rowY[depth] as number,
				w,
				h,
				isLeaf,
				depth,
			};
		});
	});
	return { layout, width: TREE_W, height: y - GAP_Y + 10 };
}

function iconSvg(
	icon: string | undefined,
	x: number,
	y: number,
	size: number,
	color: string,
): string {
	if (!icon) return "";
	const inner = ICONS[icon];
	if (!inner) return "";
	return `<svg x="${x}" y="${y}" width="${size}" height="${size}" viewBox="0 0 24 24" style="color:${color}">${inner}</svg>`;
}

// Chip folha: card branco + borda colorida + pill de nome + ícone + label.
function leafChipSvg(l: LayoutNode): string {
	const c = chipOf(l.node.color);
	const cx = l.x + l.w / 2;
	let top = "";
	if (l.node.name) {
		const pw = Math.max(44, l.node.name.length * 8.5 + 20);
		top = `<rect x="${cx - pw / 2}" y="${l.y + 12}" width="${pw}" height="22" rx="11" fill="${c.fill}"/><text x="${cx}" y="${l.y + 27.5}" text-anchor="middle" font-size="12.5" font-weight="800" fill="${c.text}">${esc(l.node.name)}</text>`;
	} else {
		top = `<rect x="${cx - 15}" y="${l.y + 16}" width="30" height="7" rx="3.5" fill="${c.stroke}"/>`;
	}
	const icon = iconSvg(l.node.icon, cx - 13, l.y + 44, 26, c.stroke);
	const label = `<foreignObject x="${l.x + 5}" y="${l.y + 78}" width="${l.w - 10}" height="${l.h - 84}"><div xmlns="http://www.w3.org/1999/xhtml" style="font:600 12.5px ${T.sans};color:${T.ink};text-align:center;line-height:1.3">${rich(l.node.label)}</div></foreignObject>`;
	return `<g><rect x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="14" fill="${T.card}" stroke="${c.stroke}" stroke-width="1.6"/>${top}${icon}${label}</g>`;
}

// Caixa: branca traço escuro; com tone → tint suave + borda da cor.
function boxNodeSvg(l: LayoutNode): string {
	const tone = l.node.tone ? chipOf(l.node.tone) : undefined;
	const fill = tone
		? `fill="${tone.fill}" fill-opacity="0.45" stroke="${tone.stroke}"`
		: `fill="${T.card}" stroke="${T.stroke}"`;
	const iconColor = tone ? tone.stroke : T.ink;
	const hasIcon = Boolean(l.node.icon);
	const icon = hasIcon
		? iconSvg(l.node.icon, l.x + 16, l.y + l.h / 2 - 10, 20, iconColor)
		: "";
	const textX = hasIcon ? l.x + 44 : l.x + 10;
	const textW = hasIcon ? l.w - 56 : l.w - 20;
	const justify = hasIcon ? "flex-start" : "center";
	const label = `<foreignObject x="${textX}" y="${l.y}" width="${textW}" height="${l.h}"><div xmlns="http://www.w3.org/1999/xhtml" style="height:100%;display:flex;align-items:center;justify-content:${justify};font:600 15px ${T.sans};color:${T.ink};text-align:${hasIcon ? "left" : "center"};line-height:1.25">${rich(l.node.label)}</div></foreignObject>`;
	return `<g><rect x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="14" ${fill} stroke-width="1.6"/>${icon}${label}</g>`;
}

function treeConnectorSvg(
	child: LayoutNode,
	parent: LayoutNode,
	markerId: string,
): string {
	const x1 = parent.x + parent.w / 2;
	const y1 = parent.y + parent.h;
	const x2 = child.x + child.w / 2;
	const y2 = child.y;
	const midY = y1 + (y2 - y1) / 2;
	const d = `M${x1},${y1} L${x1},${midY} L${x2},${midY} L${x2},${y2 - 6}`;
	return `<path d="${d}" fill="none" stroke="${T.stroke}" stroke-width="1.6" marker-end="url(#${markerId})"/>`;
}

function treeSvg(t: TreeBlock): string {
	const { layout, width, height } = layoutTree(t.nodes);
	const byId = new Map(layout.map((l) => [l.node.id, l]));
	const arrowId = nextId("tarr");
	const connectors = layout
		.filter((l) => l.node.parent && byId.has(l.node.parent))
		.map((l) =>
			treeConnectorSvg(l, byId.get(l.node.parent as string) as LayoutNode, arrowId),
		)
		.join("\n");
	const nodesSvg = layout
		.map((l) => (l.isLeaf ? leafChipSvg(l) : boxNodeSvg(l)))
		.join("\n");
	return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img">
<defs><marker id="${arrowId}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${T.stroke}"/></marker></defs>
${connectors}
${nodesSvg}
</svg>`;
}

// --- dashrow / checks / note / panel / legend ---------------------------------

function dashrowHtml(r: DashRow): string {
	const id = nextId("dash");
	return `<div class="dashrow"><svg viewBox="0 0 ${TREE_W} 24" width="100%" height="24" role="img">
<defs>
<marker id="${id}s" viewBox="0 0 10 10" refX="2" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M10,0 L0,5 L10,10 z" fill="${T.muted}"/></marker>
<marker id="${id}e" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${T.muted}"/></marker>
</defs>
<line x1="16" y1="12" x2="${TREE_W - 16}" y2="12" stroke="${T.muted}" stroke-width="1.6" stroke-dasharray="7 7" marker-start="url(#${id}s)" marker-end="url(#${id}e)"/>
</svg><p class="dashcap">${rich(r.text)}</p></div>`;
}

function checkRowHtml(c: CheckItem): string {
	const cls = c.ok ? "check check-ok" : "check check-no";
	const badge = c.ok ? "✓" : "✗";
	return `<div class="${cls}"><span class="check-badge">${badge}</span><span class="check-text">${rich(c.text)}</span></div>`;
}

const NOTE_ARROW_PATH: Record<"left" | "right" | "down", string> = {
	left: "M46,6 C20,2 6,20 6,40",
	right: "M6,6 C32,2 46,20 46,40",
	down: "M6,6 C2,20 20,34 40,40",
};

function noteHtml(n: NoteBlock): string {
	const dir = n.arrow ?? "left";
	const id = nextId("note");
	const arrow = `<svg class="note-arrow" width="52" height="46" viewBox="0 0 52 46" role="img"><defs><marker id="${id}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1971C2"/></marker></defs><path d="${NOTE_ARROW_PATH[dir]}" fill="none" stroke="#1971C2" stroke-width="2" marker-end="url(#${id})"/></svg>`;
	const before = dir === "right" ? "" : arrow;
	const after = dir === "right" ? arrow : "";
	return `<div class="note note-${dir}">${before}<p>${rich(n.text)}</p>${after}</div>`;
}

function panelHtml(p: Panel): string {
	const title = p.title ? `<h2>${rich(p.title)}</h2>` : "";
	const body = p.blocks
		.map((b) => {
			if (b.tree) return `<div class="tree-block">${treeSvg(b.tree)}</div>`;
			if (b.dashrow) return dashrowHtml(b.dashrow);
			if (b.checks)
				return `<div class="checks">${b.checks.map(checkRowHtml).join("")}</div>`;
			return "";
		})
		.join("\n");
	return `<div class="panelgrp">${title}${body}</div>`;
}

function legendHtml(items: LegendItem[]): string {
	const spans = items
		.map((it) => {
			const c = chipOf(it.color);
			return `<span><i class="sw" style="background:${c.fill};border-color:${c.stroke}"></i>${esc(it.label)}</span>`;
		})
		.join("");
	return `<div class="legend">${spans}</div>`;
}

// --- mermaid (lane de fluxo, template v2 provado) ------------------------------

// Injetados automaticamente quando o fonte não traz classDef próprio — o YAML
// só precisa de `:::purple` etc. (gramática semântica, ver SKILL.md).
const MERMAID_CLASSDEFS = `
    classDef salmon fill:#FADCD0,stroke:#E2795B,color:#7A2E17;
    classDef yellow fill:#FAE9B6,stroke:#D9A93F,color:#6B5310;
    classDef green  fill:#D4ECCF,stroke:#6FA860,color:#2F5626;
    classDef blue   fill:#C9DDF2,stroke:#5B87BC,color:#1E3A5C;
    classDef purple fill:#DFD6F1,stroke:#8F7CC4,color:#3D2D66;
    classDef paper  fill:#FFFFFF,stroke:#3A3A3A,color:#2B2B2B;`;

function mermaidScript(): string {
	return `<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
await document.fonts.load("700 15px Nunito");
await document.fonts.load("600 15px Nunito");
await document.fonts.load("800 15px Nunito");
await document.fonts.ready;
mermaid.initialize({
  startOnLoad: false, theme: 'base',
  themeVariables: {
    background: '${T.cream}',
    fontFamily: "${T.sans.replace(/"/g, "'")}",
    fontSize: '15px',
    primaryColor: '#FFFFFF', primaryTextColor: '${T.ink}', primaryBorderColor: '${T.stroke}',
    lineColor: '${T.stroke}',
    edgeLabelBackground: '#F6E7A9',
    clusterBkg: '#FFFFFF', clusterBorder: '#D8CFBE'
  },
  flowchart: { htmlLabels: true, curve: 'linear', nodeSpacing: 45, rankSpacing: 55, padding: 14 }
});
await mermaid.run();
document.title = 'RENDERED';
</script>`;
}

// --- css -----------------------------------------------------------------------

function css(): string {
	return `
${T.fontImport}
*{box-sizing:border-box}
body{margin:0;background:${T.cream};font-family:${T.sans};color:${T.ink}}
.page{max-width:1240px;margin:24px auto;background:${T.cream};border-radius:24px;padding:36px 42px 28px}
.kicker{font-weight:800;font-size:13px;letter-spacing:.16em;text-transform:uppercase;color:${T.accent};margin:0 0 8px}
h1{font-weight:800;font-size:28px;line-height:1.3;margin:0 0 4px}
.sub{font-weight:600;font-size:15px;color:${T.muted};margin:0 0 14px}
.hl{background:#F6E7A9;padding:1px 6px;border-radius:6px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.hlg{background:#D4ECCF;padding:1px 6px;border-radius:6px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.hlb{background:#C9DDF2;padding:1px 6px;border-radius:6px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.hls{background:#FADCD0;padding:1px 6px;border-radius:6px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.mono{font-family:${T.mono};font-size:.92em}
.mermaid{display:flex;justify-content:center}
.mermaid svg{font-family:${T.sans} !important}
.node rect,.node polygon,.node path{rx:12px;ry:12px;stroke-width:1.6px !important}
.edgePath path,.flowchart-link{stroke-width:1.6px !important}
.edgeLabel{border-radius:6px;font-weight:700}
.panelgrp{background:${T.card};border:1.6px solid ${T.line};border-radius:18px;padding:28px 32px 24px;margin:0 0 14px;text-align:center}
.panelgrp h2{font-weight:800;font-size:26px;margin:0 0 20px;text-align:center}
svg text{font-family:${T.sans}}
.tree-block{margin:4px 0 8px}
.tree-block svg{overflow:visible}
.dashrow{margin:8px 0 18px}
.dashcap{font-weight:600;font-size:14px;color:${T.muted};text-align:center;margin:8px 0 0}
.checks{display:flex;flex-direction:column;gap:8px;margin:14px 0 4px;text-align:left}
.check{display:flex;align-items:center;gap:12px;padding:10px 14px;border-radius:10px;font-size:15px}
.check-ok{background:#EFFBF1}
.check-no{background:#FBEAE8}
.check-badge{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;font-size:12px;font-weight:800;color:#fff;flex:0 0 auto}
.check-ok .check-badge{background:#2F9E44}
.check-no .check-badge{background:#E03131}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 4px;font-weight:700;font-size:12.5px;color:#5C554B}
.legend span{display:flex;align-items:center;gap:6px}
.sw{width:18px;height:13px;border-radius:4px;border:1.6px solid;display:inline-block}
.note{display:flex;align-items:center;gap:8px;max-width:360px;margin:2px 0 14px;font-family:${T.hand};color:#1971C2;font-size:24px;line-height:1.2}
.note p{margin:0}
.note-right{margin-left:auto;flex-direction:row-reverse;text-align:right}
.note-down{flex-direction:column;text-align:center;max-width:240px;margin:2px auto 14px}
.note-arrow{flex:0 0 auto}
.band{background:${T.charcoal};color:${T.cream};border-radius:12px;padding:13px 18px;font-weight:700;font-size:16.5px;margin:12px 0 10px}
.band .hl,.band .hlg,.band .hlb,.band .hls{background:none;padding:0;color:#F6E7A9}
.foot{display:flex;justify-content:space-between;font-weight:800;font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:${T.footMuted};border-top:1.6px solid ${T.line};padding-top:9px;margin-top:4px}
`;
}

// --- render -----------------------------------------------------------------

const BLOCKS: [keyof Doc, (d: Doc) => string][] = [
	["kicker", (d) => `<p class="kicker">${esc(d.kicker ?? "")}</p>`],
	["headline", (d) => `<h1>${rich(d.headline ?? "")}</h1>`],
	["sub", (d) => `<p class="sub">${rich(d.sub ?? "")}</p>`],
	[
		"mermaid",
		(d) => {
			const src = d.mermaid ?? "";
			const full = src.includes("classDef") ? src : src + MERMAID_CLASSDEFS;
			return `<pre class="mermaid">\n${full}\n</pre>`;
		},
	],
	["panel", (d) => (d.panel ? panelHtml(d.panel) : "")],
	[
		"tree",
		(d) => (d.tree ? `<div class="tree-block">${treeSvg(d.tree)}</div>` : ""),
	],
	["dashrow", (d) => (d.dashrow ? dashrowHtml(d.dashrow) : "")],
	[
		"checks",
		(d) =>
			d.checks
				? `<div class="checks">${d.checks.map(checkRowHtml).join("")}</div>`
				: "",
	],
	["legend", (d) => (d.legend ? legendHtml(d.legend) : "")],
	["note", (d) => (d.note ? noteHtml(d.note) : "")],
	["band", (d) => `<div class="band">${rich(d.band ?? "")}</div>`],
	[
		"footer",
		(d) =>
			d.footer
				? `<div class="foot"><span>${esc(d.footer.left ?? "")}</span><span>${esc(d.footer.right ?? "")}</span></div>`
				: "",
	],
];

function render(d: Doc): string {
	const parts = BLOCKS.filter(([key]) => d[key]).map(([, build]) => build(d));
	const ready = d.mermaid
		? mermaidScript()
		: `<script>document.fonts.ready.then(()=>{document.title='RENDERED'})</script>`;
	return `<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><title>${esc(d.title ?? "poster")}</title><style>${css()}</style></head><body><div class="page">\n${parts.join("\n")}\n</div>${ready}</body></html>`;
}

async function exportPng(htmlPath: string): Promise<string> {
	// Dynamic import (exceção deliberada): playwright é dependência opcional e
	// pesada, só usada com --png; import estático quebraria o modo HTML-only.
	const { chromium } = await import("playwright");
	const browser = await chromium.launch();
	const page = await browser.newPage({
		viewport: { width: 1400, height: 1100 },
		deviceScaleFactor: 2,
	});
	await page.goto(`file://${resolve(htmlPath)}`, { waitUntil: "load" });
	await page.waitForFunction('document.title === "RENDERED"', { timeout: 30000 });
	// O mermaid seta o title ANTES de o compositor pintar o SVG; rAF não basta —
	// só uma espera real deixa o frame chegar à surface (800ms validado 2026-07-19).
	await page.waitForTimeout(800);
	const pngPath = htmlPath.replace(/\.html$/, ".png");
	const el = await page.$(".page");
	if (!el) throw new Error(".page não encontrado");
	const box = await el.boundingBox();
	if (!box) throw new Error(".page sem boundingBox");
	await page.screenshot({ path: pngPath, clip: box, fullPage: true });
	await browser.close();
	return pngPath;
}

const args = process.argv.slice(2);
const input = args.find((a) => !a.startsWith("-"));
if (!input) {
	console.error("uso: bun pastelgen.ts input.yaml [-o out.html] [--png]");
	process.exit(1);
}
const outFlag = args.indexOf("-o");
const out: string =
	outFlag >= 0 && args[outFlag + 1]
		? (args[outFlag + 1] as string)
		: input.replace(/\.ya?ml$/, ".html");
const doc = Bun.YAML.parse(await Bun.file(input).text()) as Doc;
await Bun.write(out, render(doc));
console.log(out);
if (args.includes("--png")) console.log(await exportPng(out));
