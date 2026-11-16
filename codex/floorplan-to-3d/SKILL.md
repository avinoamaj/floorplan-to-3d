---
name: floorplan-to-3d
description: Turn a floor-plan image or PDF with written dimensions into a precise 2D verification overlay (stage 1, then stop for approval) and then an interactive three.js 3D model (stage 2) with real wall openings, furniture, orbit/top/walk views and a measuring tool. Use when the user gives a floor plan, room plan or apartment layout (תוכנית דירה, תוכנית חדר, שרטוט) and wants it verified, measured, modelled in 3D or walked through.
---

# Floor plan → verified 2D overlay → 3D model (Codex / ChatGPT)

Two stages with a hard stop between them. Precision and repeatability come from one rule: **all geometry lives in one `model.json`, and every page is generated from it by `scripts/fp.py`** (bundled in this skill folder). Never hand-write page HTML and never do unit conversions in your head. Your job is to read the plan correctly and fill `model.json`. The scripts measure, check, render and freeze it.

## Ground rules
- Written dimensions on the plan are the only source of truth. Never measure pixels to set a written dimension, and never "fix" a written number that disagrees with the drawing. Report the disagreement instead.
- Anything without a written dimension may be placed by scale, but it is marked as an estimate (orange).
- Don't guess. An unreadable number, a dimension that cannot be tied to one segment, or an unclear wall or opening gets a red mark plus a question.
- Work in cm. Identify the plan's unit and whether dimensions run to wall centrelines, inside faces or outside faces.
- Colours: black = from a written dimension, orange = estimated from scale, red = uncertain or a failed check (with a short label explaining it).
- Include all furniture and fixtures drawn on the plan in both stages, unless the user says otherwise.
- Stage 2 uses exactly the approved stage-1 model, with no "improvements". `build2` enforces this with a hash.
- Reply in the user's language. Set `meta.lang` to `he` or `en` so the pages match.

## Setup
`SK` is the folder that contains this SKILL.md; it holds `scripts/`, `assets/` and `references/`.
```bash
FP="python3 $SK/scripts/fp.py"          # on Windows: py "%SK%\scripts\fp.py"
python3 -c "import PIL, numpy"           # required; scipy is optional but faster
```
- **Missing packages:** if the import fails, run `pip install pillow numpy scipy`. If the sandbox has no network, ask the user to run that command (or to approve network access). Don't work around it.
- **Working folder:** work in a new folder next to the plan (e.g. `floorplan-<name>/`) and copy the plan in.
- **PDF input:** render page 1 to PNG at about 150–200 dpi first (`pdftoppm -png -r 170`, or ask the user for a PNG export).
- **Don't open `fp.py` or the templates.** `$FP <cmd> -h` documents every command.

Before writing model.json for the first time, read `$SK/references/method.md` (how to read plans and the pitfalls) and `$SK/references/model_schema.md` (exact fields).

To look at the plan or a crop, use your image-viewing tool (for example `view_image`) on the PNG file. If you can't view images, ask the user to attach the plan to the conversation.

## Stage 1: 2D verification drawing
Keep a plan or checklist of these steps.

1. **Read the plan.** View the image. Note:
   - the unit (`'`/`"` = ft/in, or m/cm/mm);
   - every written dimension and its position;
   - room labels, doors, windows and furniture.

   A bracketed placeholder in the user's message (e.g. a ceiling height written as `[e.g. 260 cm…]`) counts as not given.
2. **Find the walls.** `$FP info plan.png` gives the wall colour. Then `$FP walls plan.png --rgb R,G,B -o walls.json` lists every wall line (H = horizontal, V = vertical) with its centre, thickness and gaps.
3. **Register.** Map wall lines to grid coordinates from the written dimensions in `pairs.json`, e.g. `{"unit":"ft","walls":"walls.json","x":[[0,"V1"],[8,"V2"],…],"y":[[0,"H1"],…]}`. Run `$FP fit pairs.json -o reg.json`.
   - The residual must be ≤ 1.5 px.
   - `reference_test` tells you which dimension reference the drawing follows.
   - `thickness_estimate_cm` is the wall-thickness estimate to use.
4. **Measure the estimates.**
   - Openings come from the `walls` gaps.
   - For furniture and fixtures use `$FP bbox plan.png --region x1,y1,x2,y2` (`--mode green` for plants, `--components` when pieces touch).
   - Only when something is ambiguous, look closer: `$FP crop plan.png --region … -o c.png`, then view the crop.
5. **Write `model.json`** following the schema: walls, rooms, openings, dims (every written number, verbatim), chains, items, flags, questions and notes. Leave out `heights` and `approval`.
6. **Check.** Run `$FP check model.json`.
   - A failure caused by a wrong mapping or a typo is yours to fix.
   - A failure caused by the plan itself stays in. It gets a red mark and a question.
7. **Build.** `$FP build1 model.json --image plan.png -o stage1.html`. If Playwright is installed, run `$FP shoot stage1.html -o s1.png --modes both` and view the screenshot. Check that the overlay sits on the original walls and that no red note collides with another (`--full` also shows the questions and tables). Rebuild only if something is wrong.
8. **Deliver and STOP.** Give the user `stage1.html`: as a downloadable file if your environment offers that (ChatGPT), otherwise its path, to open in any browser (on macOS: `open stage1.html`). Then, in the user's language:
   - one line on what the page shows;
   - the open questions, numbered and short, each with the assumption you made meanwhile.

   Then end your turn and wait. Do not start stage 2 in the same turn.

## Between the stages
- **Corrections:** edit `model.json`, run `check`, rebuild stage 1, tell the user it's updated, and wait again.
- **Approval:** apply only what the user approved or answered (for example removing a flag they dismissed, or the values they gave). Then set `heights`:
  - values the user gave: `source: "user"`;
  - anything still unanswered: the defaults 260/210/90/210 with `source: "default"`. Say they are defaults the user can change live on the page.

  Then run `$FP approve model.json`.
- **Late requests:** if the user asks for something stage 1 left out, add it to `model.json`, rebuild stage 1, and get approval before stage 2. The 3D model never contains anything unapproved.

## Stage 2: 3D model
1. **Build:** `$FP build2 model.json -o model3d.html`. It refuses if the model changed after `approve`, or if heights are missing. The page loads three.js 0.160.0 from jsDelivr, so the user's browser needs internet access.
2. **Optional check** (needs npm and Playwright):
   - `npm i --prefix ./t3 three@0.160.0`
   - `$FP build2 model.json -o test3d.html --three-local ./t3/node_modules/three`
   - `$FP shoot test3d.html -o s2.png --modes orbit,top,walk`

   View one or two screenshots. Never hand the test build to the user: its import paths only work through `shoot`'s local server.
3. **Deliver** `model3d.html` the same way (download or path) with a short summary:
   - what the page offers: orbit, top and walk views (walk at 160 cm eye height), the measuring tool with snapping, toggles for ceiling, dimensions, room names, furniture and door leaves, and live height inputs;
   - which values are defaults;
   - one sanity measurement, e.g. inside width = overall − one outer wall thickness.

## Consistency habits
- Same order every time: info → walls → fit → bbox → model.json → check → build1. Use the ids that `walls` gives you.
- Copy each estimate straight from script output, not re-measured by eye.
- After feedback, change model.json, never a page.
- Keep replies short. The page carries the details: checks, walls, openings and items tables.
