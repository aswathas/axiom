# AXIOM UI — Next.js + Recharts

Clinician surface for the AXIOM pipeline.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
npm run build      # static prerender
```

## Regenerate the fixture

The UI reads **only** `public/fixture.json`. It computes no clinical numbers.

```bash
cd /workspace && python3 -m axiom.export
```

Never hand-edit fixture data — regenerate it.

## Verify

```bash
node verify.mjs    # fixture → UI contract, all scenes
```

## Screens

| Screen | Beat | What it renders |
|---|---|---|
| Patient chart | 0:00 | Header, attention queue, permanent safety boundary |
| Evidence card | 0:10 | Claim + clickable citations → source drawer + trend chart |
| Interaction | 0:25 | Verified claims, contraindications, graph stats |
| **THE TURN** | **0:40** | **Refusal screen — the beat that differentiates** |
| Benchmark | 0:55 | Metrics, robustness sweep, what we missed, limitations |

## Architecture

- App Router, static prerender (`○ (Static)`) — no server needed to view
- Recharts for the trend line and robustness bars
- Custom SVG lane chart for the temporal graph
- `fixture.json` is the single data contract; UI renders, never calculates

## Data posture

100% synthetic. No real PHI. The generator is published alongside this app.
