---
name: floorplan-to-3d
description: Turn a floor-plan image or PDF with written dimensions into a precise 2D verification overlay (stage 1, then stop for approval) and then an interactive Three.js 3D model (stage 2) with real wall openings, furniture, orbit/top/walk views and a measuring tool. Use whenever the user uploads a floor plan, room plan, apartment or house layout (תוכנית דירה, תוכנית חדר, שרטוט) and wants it verified, measured, modelled, built in 3D, or walked through, even if they only say "make this plan 3D" or "check the dimensions of this plan".
---

# Floor plan → verified 2D overlay → 3D model

Two stages with a hard stop between them. Precision and repeatability come from one rule: **all geometry lives in one `model.json`, and every page is generated from it by `scripts/fp.py`**. You never hand-write page HTML and never do unit conversions in your head. Your job is to read the plan correctly and fill `model.json`. The scripts measure, check, render and freeze it.

## Ground rules (from the user who commissioned this skill)
- Written dimensions on the plan are the only source of truth. Never measure pixels to set a written dimension, and never "fix" a written number that disagrees with the drawing. Report the disagreement instead.
- Anything without a written dimension may be placed by scale, but it is marked as an estimate (orange).
- Don't guess. An unreadable number, a dimension that cannot be tied to one segment, or an unclear wall or opening gets a red mark plus a question.
- Work in cm. Identify the plan's unit and whether dimensions run to wall centrelines, inside faces or outside faces.
- Colours: black = from a written dimension, orange = estimated from scale, red = uncertain or a failed check (with a short label explaining it).
- Include all furniture and fixtures drawn on the plan in both stages, unless the user says otherwise.
- Stage 2 uses exactly the approved stage-1 model, with no "improvements". `build2` enforces this with a hash.

## Setup (once per session)
The toolkit (scripts, page templates, references) lives next to this file when the skill is installed as a package; otherwise fetch the pinned release from GitHub:
```bash
SK=<folder of this SKILL.md>
if [ ! -f "$SK/scripts/fp.py" ]; then
  SK=/tmp/fp3d; [ -f $SK/scripts/fp.py ] || git clone -q --depth 1 --branch v1 https://github.com/avinoamaj/floorplan-to-3d $SK
fi
FP="python3 $SK/scripts/fp.py"
python3 -c "import PIL, numpy" 2>/dev/null || pip install -q --break-system-packages pillow numpy scipy
```
Needs PIL and numpy (scipy recommended). Work in a fresh directory and copy the plan there. Only `scripts/`, `assets/` and `references/` matter at run time; ignore `evals/` (tests for the skill itself). For a PDF, render page 1 to PNG at about 150–200 dpi first (`pdftoppm -png -r 170`). Do not open `fp.py` or the templates: `$FP <cmd> -h` documents every command.

Before writing model.json for the first time, read `$SK/references/method.md` (how to read plans and the pitfalls) and `$SK/references/model_schema.md` (exact fields).

## Stage 1: 2D verification drawing
Track these steps in a task list.

1. **Read the plan.** Look at the image. Note the unit (`'`/`"` = ft/in, or m/cm/mm), every written dimension with its position, room labels, doors, windows and furniture. Treat a bracketed placeholder in the user's message (e.g. a ceiling height written as `[e.g. 260 cm…]`) as not given.
2. **Find the walls.** `$FP info plan.png` gives the wall colour. Then `$FP walls plan.png --rgb R,G,B -o walls.json` lists every wall line (H = horizontal, V = vertical) with centre, thickness and gaps.
3. **Register.** Map wall lines to grid coordinates from the written dimensions, in `pairs.json`: `{"unit":"ft","walls":"walls.json","x":[[0,"V1"],[8,"V2"],…],"y":[[0,"H1"],…]}`. Run `$FP fit pairs.json -o reg.json`. The residual must be ≤ 1.5 px. `reference_test` tells you which dimension reference the drawing follows; `thickness_estimate_cm` is the wall-thickness estimate to use.
4. **Measure the estimates.** Openings come from the `walls` gaps. For furniture and fixtures use `$FP bbox plan.png --region x1,y1,x2,y2` (`--mode green` for plants). Only when something is ambiguous, look closer with `$FP crop plan.png --region … -o c.png` and Read the crop.
5. **Write `model.json`** following the schema: walls, rooms, openings, dims (every written number, verbatim), chains, items, flags, questions, notes. Leave out `heights` and `approval`.
6. **Check.** `$FP check model.json`. A failure caused by a wrong mapping or a typo is yours to fix. A failure caused by the plan itself stays in, and gets a red mark and a question.
7. **Build and look.** `$FP build1 model.json --image plan.png -o stage1.html`. If playwright is available, run `$FP shoot stage1.html -o s1.png --modes both` (it sizes itself to the whole drawing; `--full` instead captures drawing + questions + tables) and view it to confirm the overlay sits on the original walls and no red note collides with another. Fix in model.json, rebuild, and look again only if something is wrong.
8. **Deliver and STOP.** Publish `stage1.html` as an artifact if an artifact or publish tool exists, otherwise send the file. In your reply, in the user's language: one line on what the page shows, then the open questions, numbered and short, each with the assumption you made meanwhile. Then stop and wait. Do not start stage 2 in the same turn.

## Between the stages
- **Corrections:** edit `model.json`, run `check`, rebuild stage 1, show it again, and wait again.
- **Approval:** apply only what the user approved or answered (removing a flag they dismissed, the values they gave). Then set `heights`:
  - values the user gave → `source: "user"`;
  - anything still unanswered → defaults 260/210/90/210 with `source: "default"`, and tell the user these are defaults they can change live in the panel.
  - Then run `$FP approve model.json`.
- **Late requests:** if the user asks for something stage 1 left out (for example furniture), add it to `model.json`, rebuild stage 1, and get approval before stage 2. The stage-2 model never contains anything unapproved.

## Stage 2: 3D model
1. `$FP build2 model.json -o model3d.html`. It refuses if the model changed after `approve` or if heights are missing. It loads three.js 0.160.0 from jsDelivr.
2. **Optional check:** `npm i --prefix /tmp/t3 three@0.160.0`, then `$FP build2 model.json -o test3d.html --three-local /tmp/t3/node_modules/three`, then `$FP shoot test3d.html -o s2.png --modes orbit,top,walk`. Glance at one or two screenshots; never publish the test build.
3. **Publish** `model3d.html` as before. Reply with a short summary:
   - what the page offers: orbit, top and walk views (walk at 160 cm eye height), the measuring tool with snapping, toggles for ceiling, dimensions, room names, furniture and door leaves, and live height inputs;
   - which values are defaults;
   - one sanity measurement, e.g. the inside width = overall − one outer wall thickness.

## Model page features (built into the template; don't re-implement)
- Walls raised to ceiling height with real openings: door heads, window sills and window heads.
- Room floors with finishes, and a ceiling that can be hidden.
- Open door leaves as drawn, window frames and glass.
- Fixtures and furniture built from the catalog in the schema.
- Labels hidden behind walls; the panel can be collapsed; Hebrew or English UI via `meta.lang`.

## Consistency habits
- Same order every time: info → walls → fit → bbox → model.json → check → build1. Use the ids that `walls` gives you.
- Each estimate is copied straight from script output, not re-measured by eye.
- When you change something after feedback, change model.json, not a page.
- Keep the conversation reply short. The page carries the details: checks table, walls table, openings table, items table.
