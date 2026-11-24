# Nexus Grid: UI design brief

One responsive UI for the browser and the desktop worker window (the desktop client is the same page in a native window; only the window controls are added to the top bar). Reference screens in this folder:

- `observer.png`: Observer mode, job in progress
- `failover.png`: a worker dies, its tiles are reassigned
- `my-worker.png`: My Worker view (local compute client)
- `compact.png`: compact layout under 960px

Build the UI to match these screens. Dark, strict, mission-control feel. All text in English.

## Layout (1280x720 to 1920x1080)

- Top bar, fixed 56px: logo, live connection dot with status text, segmented switch Observer / My Worker, Demo Mode button, masked API key with reveal/copy, settings.
- HUD strip, 84px: 5 equal cards (Tasks/sec, Latency, Alive Workers n/n, Queue Depth, Jobs Done), tabular numbers, 60 s sparkline each.
- Main area (about 68% width): Mandelbrot mosaic (192 tiles) and worker graph side by side, per-worker telemetry under them (CPU, memory or temperature, throughput, latency, worker color chips).
- Right column, 320 to 360px: Active Job (type Mandelbrot / Image Batch, priority, progress, Cancel, Download), Workers list (status, load bar, tasks, heartbeat age), Event feed.
- Mosaic: finished tiles carry a 22% tint of the color of the worker that computed them, pending tiles are dark, active tiles pulse, hover shows worker and compute time ("Atlas-01 · 184ms").
- My Worker view: large radial load gauge, current task card with tile coordinates and live preview, 4 chips (Tasks Done, Avg Time, Uptime, Cluster Share); right side has Server URL, masked API key, Worker name, Connect/Disconnect, state badge, Auto-Reconnect toggle, activity log.
- Under 960px: mode switch becomes a full-width bar, HUD becomes a 2x2 grid, mosaic stays the hero with inline progress and actions, graph / workers / charts / feed go into one tabbed panel above a one-line live event ticker.

## States

| State | Treatment | Action |
|---|---|---|
| Empty (0 workers) | Server hub alone with soft idle rings, dark 192-tile wireframe, glass callout "No compute nodes connected." | Switch to My Worker (primary), Launch Demo Mode (violet outline) |
| Reconnecting | Amber dot with fast pulse ("Reconnecting · Attempt 2/5"), HUD dimmed to 55% and frozen, 2px amber indeterminate bar under the top bar, last mosaic frame kept | Retry Now link |
| Server sleeping (free host cold start, about 60 s) | Centered glass card, elapsed timer (00:24 / ~01:00), 3 steps (Spinning up container, Booting coordinator, Opening WebSocket), orbital pulse ring | Opens the workspace when /api/health returns 200; optional Demo Mode while waiting |
| Error | 40px crimson top banner with code (AUTH_401 Invalid API Key, WS_1006 Cluster Unreachable), red dot, affected panel borders red | Update API Key or Reconnect, copy diagnostic log |

## Failure sequence (the key moment)

Within about 3 seconds of missed heartbeats the dead worker turns crimson on four surfaces at once: HUD (Alive Workers 3/4, red-amber border, sparkline drop), graph (red node, dashed red link, OFFLINE badge), workers list (red row, "Lost · 5.2s"), event feed (red fault entry and amber "tiles reassigned" entry). Orphaned tiles flash red-amber in the mosaic and glowing arcs fly from the dead worker through SERVER to the healthy workers.

## Motion spec

Animate only GPU-friendly properties (transform, opacity, stroke-dashoffset, clip-path, CSS variables), 60 fps, no layout reflow.

| Element | What animates | Trigger | Duration | Easing |
|---|---|---|---|---|
| Tile fill-in | opacity 0 to 1, scale 0.92 to 1, 1px worker-color inner flash fading 0.9 to 0.22 alpha | result received | 220ms settle, 380ms tint flash | cubic-bezier(0.16, 1, 0.3, 1) |
| Active tile pulse | inner border opacity 0.35 to 1 to 0.35, glow 0 0 8px to 0 0 14px | task in progress | 1400ms loop | cubic-bezier(0.4, 0, 0.2, 1) |
| Graph link pulses | 6px glowing dot travels along a Bézier path; cyan server to worker, violet or worker color worker to server | task dispatch, result upload | 450 to 700ms, scaled by link latency | linear |
| Worker failure | ring and glow snap to #EF4444, horizontal damped shake (0, -6, 6, -4, 4, -2, 0 px), link becomes dashed red with dashoffset receding | heartbeat timeout (default 5 s) | 420ms shake, 180ms color snap | cubic-bezier(0.36, 0.07, 0.19, 0.97) |
| Tile reassignment | 10x10px glowing chips fly on quadratic arcs from dead worker's tiles via SERVER to receiving workers, scale 1.0, 1.15, 0.6 on arrival | tasks reassigned event | 650ms per arc, 40ms stagger, max 8 at once | cubic-bezier(0.22, 1, 0.36, 1) |
| HUD counters | vertical odometer roll on changed digits only (tabular-nums) | metric tick (250 to 500ms) | 260ms | cubic-bezier(0.2, 0.8, 0.2, 1) |
| Sparklines | mount: stroke-dashoffset reveal left to right; live: horizontal pan, new point appended | panel mount, 1 s sample | 550ms draw, 300ms pan | cubic-bezier(0.25, 1, 0.5, 1) mount, linear live |
| Progress bar shimmer | diagonal highlight rgba(255,255,255,0.28) sweeps translateX(-100% to 200%), width interpolates | job running (0 to 100%) | 1800ms sweep loop, 320ms width | linear sweep, cubic-bezier(0.16, 1, 0.3, 1) width |
| Event feed item | translateY(-12px to 0), opacity 0 to 1, 1px left accent fading 1.0 to 0.3 | any cluster event | 240ms entry, 900ms highlight decay | cubic-bezier(0.16, 1, 0.3, 1) |
| Status dot | halo ring scale 1 to 2.4 while opacity 0.75 to 0 | connected (green) or reconnecting (amber) | 2000ms connected, 900ms reconnecting | cubic-bezier(0, 0, 0.2, 1) |
| Demo Mode button glow | violet to cyan border luminance breathes, box-shadow alpha 0.25 to 0.55 to 0.25 | idle with 0 real workers; stops after click or when workers join | 2800ms loop | ease-in-out |
| Page load stagger | top bar 0ms, HUD cards 40ms each, mosaic and graph 160ms, telemetry and sidebar 240ms; opacity 0 to 1, translateY 8px to 0 | app mount, mode switch | 280ms per layer, total up to 520ms | cubic-bezier(0.16, 1, 0.3, 1) |
| Hover and focus | cards and buttons: brighter border, translateY(-1px); mosaic tile: crisp 1.5px frame, tooltip fades and scales 0.96 to 1; keyboard focus: 2px #22D3EE ring with 2px offset | pointer hover, :focus-visible | 120ms hover, 100ms tooltip, 140ms focus | cubic-bezier(0.2, 0, 0, 1) |
| Skeleton loading | gradient wave #11192E, #1C2744, #11192E across placeholders shaped like HUD cards, mosaic grid, worker rows | first handshake or fetch over 150ms | 1500ms loop | ease-in-out |
| Server waking up | concentric radar rings around the Nexus core icon, scale 0.85 to 1.6, opacity 0.5 to 0; steps fill in sequence; timer ticks every 1000ms | HTTP 503 or cold-start probe | 2600ms radar loop, 300ms step transition | cubic-bezier(0.4, 0, 0.2, 1) |

### prefers-reduced-motion: reduce

Keep all meaning, remove vestibular triggers.
- Disabled: failure shake, flying reassignment chips, HUD digit rolls, load stagger, Demo button breathing, progress shimmer, skeleton sweep, radar waves, status dot halo.
- Replacements: tile fill-in and reassignment become a 120ms opacity crossfade, reassigned tiles show a static amber-to-new-color border for 1200ms; active tiles and status dot use solid borders with micro-labels (COMPUTING, ONLINE, RECONNECTING); failed worker gets a crimson border, OFFLINE pill and static dashed red link; graph links show static arrowheads with opacity from throughput (0.25 idle to 0.95 peak); counters and feed update in place with a 150ms background tint on critical events; the waking-up state is a static checklist with a numeric countdown.

## Design tokens

Colors

| Token | Value | Use |
|---|---|---|
| --bg-canvas | #050811 | app backdrop |
| --bg-surface-1 | rgba(13, 20, 36, 0.72) | glass panels |
| --bg-surface-2 | rgba(20, 30, 52, 0.84) | elevated cards, tooltips, dropdowns, active inputs |
| --bg-tile-pending | #0B1120 | uncomputed tile |
| --border-subtle | rgba(148, 163, 184, 0.14) | 1px panel border |
| --border-glow-cyan | rgba(34, 211, 238, 0.38) | active panels, focus, selected tabs |
| --border-glow-red | rgba(239, 68, 68, 0.55) | failed worker, offline rows, error banner |
| --text-primary | #F1F5F9 | headings, metrics |
| --text-secondary | #94A3B8 | card titles, axis labels, metadata |
| --text-muted | #64748B | disabled, placeholders, grid lines |
| --accent-primary | #22D3EE | actions, active nav, outbound flow |
| --accent-secondary | #8B5CF6 | Demo Mode, gauge gradient, inbound flow |
| --status-healthy | #10B981 | connected, healthy workers |
| --status-warning | #F59E0B | reconnecting, high queue, reassignment |
| --status-failed | #EF4444 | dead worker, timeout, errors |
| --worker-palette | #22D3EE, #A78BFA, #34D399, #FBBF24, #F472B6, #60A5FA | worker chips and 22% tile tints (stable per worker) |

Typography: UI font Inter (system sans fallback); data font JetBrains Mono or Inter, always with `font-variant-numeric: tabular-nums`.

| Token | Size / line | Weight | Letter spacing | Use |
|---|---|---|---|---|
| --text-kpi-hero | 40/44 | 700 | -0.03em | My Worker gauge percentage |
| --text-kpi | 24/28 | 600 | -0.02em | HUD figures |
| --text-title | 15/20 | 600 | -0.01em | panel headers |
| --text-body | 13/18 | 400, 500 | 0 | names, buttons, inputs, event rows |
| --text-label | 11/16 | 600 | +0.06em | uppercase micro-labels, badges |
| --text-mono-xs | 11/15 | 500 | 0 | timestamps, coordinates, heartbeat age, chart ticks |

Spacing (8px grid): 4 (micro gaps, tile gutter), 8 (compact rows, badges), 12 (input padding, HUD gap), 16 (panel padding, grid gutter), 20 (outer margin at 1920), 24 (hero padding), 32 (empty and cold-wake spacing).

Radius: 4 (tiles), 8 (buttons, inputs, rows, tooltips), 12 (HUD cards, segmented controls), 16 (main glass panels, modals), 9999 (dots, chips, pills, toggles).

Elevation and glass
- Panel blur: `blur(16px) saturate(140%)`; overlay blur: `blur(24px) saturate(160%)`
- Panel shadow: `0 8px 32px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.06)`
- Tooltip shadow: `0 12px 28px rgba(0,0,0,0.65)`
- Glows: cyan `0 0 16px rgba(34,211,238,0.28)`, violet `0 0 18px rgba(139,92,246,0.35)`, red `0 0 20px rgba(239,68,68,0.45)`

## Implementation notes for Claude Code

- Keep one page, no heavy framework; canvas or SVG for the mosaic, graph and sparklines.
- Desktop worker: the same page in a native window (for example pywebview), with the Python worker running beside it; the My Worker view talks to the local worker.
- Use only fonts that need no card or paid service (Inter and JetBrains Mono are open source; bundle or fall back to system fonts).
- The screens are concept art: names, numbers and the `wss://grid.nexus-compute.io` address in them are placeholders, not real data.
