# UI design contract — Support Agent Tools ("Trajectory")

Family: dark ops console shared across the portfolio (Sora display / Public Sans body /
JetBrains Mono data, self-hosted woff2 inlined by `scripts/inline_fonts.py`).
Edit `src/static/ui.src.html`, regenerate with `python scripts/inline_fonts.py`.

## Palette (OKLCH-tuned hex)

- `--bg: #0B0F14` · `--panel: #10161D` · `--raised: #151D26`
- `--line: rgba(233,237,242,.09)` · `--text: #E8EDF2` · `--muted: #93A1B0`
- `--accent: #34C77B` (emerald — action/go; the ONE accent)
- Status: resolved emerald, escalated amber `#E5A13D`, error `#E5484D`
- Contrast: body ≈13:1, muted ≈7:1 on panel (≥4.5 ✓)

## Layout concept

"Mission control": customer chat left, live agent trajectory right. The rail
builds itself event-by-event from the real SSE stream — the recruiter watches
the agent think, call tools, hand off, and resolve.

```text
+--------------------------------------------------------------+
| ◈ Support Agent Tools     mock LLM · PII redacted in/out     |
+------------------------------+-------------------------------+
| SAMPLE CHIPS (4)             |  TRAJECTORY                   |
| [customer msg →]             |  ● triage → support           |
| [← agent answer]             |  ● kb_search {…} ✓ 42ms       |
| [input_____________] [Send]  |  ● db_create_ticket ✓ #4      |
|                              |  ✔ resolved · 4 iterations    |
+------------------------------+-------------------------------+
```

## Bold element

The trajectory timeline itself: mono tool names with expandable JSON args,
pulse-on-arrival, handoff connectors. The chat is deliberately plain so the
rail carries the "wow, it really acts" moment.

## Motion

- Load stagger; message slide-in; typing dots while SSE connects
- Timeline nodes pop + connector draws as events arrive (real stream timing)
- Escalation: rail node turns amber, chat shows handoff notice
- `prefers-reduced-motion`: everything appears instantly, no animation

## States

idle · streaming (live nodes) · resolved · escalated · error/422 (shows detail + retry).
Mobile ≤900px: rail stacks below chat; 390px verified no overflow.
