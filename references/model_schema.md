# model.json — schema and conventions

`model.json` is the single source of truth. Both pages are generated from it by `fp.py`; nothing in a page is typed by hand. Keep it in the working directory next to the plan image.

## Coordinate system
- **Plan units** (the unit written on the plan) for everything that comes from a written dimension: wall endpoints, room polygons, dimension segments, chains.
- Origin `[0,0]` = the top-left corner of the outer walls *at the dimension reference* (normally the outer-wall centreline corner). x grows right, y grows **down** (same as the image).
- **Pixels** (`*_px`) for everything estimated from scale: openings without written positions, furniture, fixtures, label positions, flags. `fp.py` converts px → cm with `registration`; you never convert by hand.
- cm in the resolved output: `cm = plan_value × unit_cm` (ft 30.48, in 2.54, m 100, cm 1, mm 0.1).

## Top level
```json
{
 "meta": {"title": "...", "unit": "ft|in|m|cm|mm", "dim_reference": "centerline|interior|exterior",
          "lang": "he|en", "image": "plan.png", "wall_rgb": [128,128,128], "walk_start_cm": [x,y]},
 "registration": {"s": 0.8018, "ox": 257.6, "oy": 159.1, "max_residual_px": 0.25},
 "thickness": {"out": {"cm": 24, "status": "estimate"}, "in": {"cm": 16, "status": "estimate"}},
 "walls": [], "rooms": [], "openings": [], "dims": [], "chains": [], "items": [],
 "flags": [], "questions": [], "notes": [],
 "heights": {"ceiling": 260, "door_head": 210, "window_sill": 90, "window_head": 210,
             "source": {"ceiling": "user|default", "door_head": "...", "window_sill": "...", "window_head": "..."}},
 "approval": {"approved": true, "sha256": "...", "at": "...", "by": "user"}
}
```
- `registration`: paste the `s, ox, oy, max_residual_px` written by `fp.py fit -o reg.json`.
- `thickness`: take `thickness_estimate_cm` from the `fit` output (status `estimate`) unless written numbers give it (`written`/`derived`). Meaning: `px = ox + s·cm_x`, `py = oy + s·cm_y`.
- `meta.lang`: language of the pages' UI (match the user's language). `walk_start_cm` optional (default: centroid of the largest room).
- `heights`: leave out until stage 2. `approval`: written only by `fp.py approve`.

## walls
```json
{"id": "W1", "kind": "out|in", "a": [0,0], "b": [40,0], "desc": "top outer",
 "t_cm": 20, "t_status": "written", "status": "written"}
```
- Straight segments between centreline points (axis-aligned or oblique). Split a wall wherever its thickness or kind changes; a T-junction does **not** need a split (the stem just ends on the other wall).
- `kind` picks the thickness from `thickness`. `t_cm`/`t_status` override per wall (e.g. a written wall thickness).
- Thickness `status`: `written` (printed on the plan), `derived` (follows arithmetically from written numbers, e.g. overall 780 − centreline chain 750 = 30 cm outer walls — prefer this over a pixel estimate), `estimate` (from pixels: `thickness_px / s`, rounded half-up to whole cm).
- `status`: `written` (default) or `uncertain` (wall drawn red — use when the wall itself is unclear).
- Walls must form a connected network: every end must touch another wall, outer walls must close a loop (`check` verifies).

## rooms
```json
{"id": "bed1", "name": "BEDROOM 1", "label": "12'- 0\"x13'- 0\"", "poly": [[0,12],[12,12],[12,25],[0,25]],
 "size": [12,13], "label_px": [484,608], "floor": "wood|tile|carpet|concrete", "show_label": true}
```
- `poly` on the dimension grid (centrelines). Copy `name`/`label` text verbatim from the plan.
- `label_px` = centre of the **name line** (first line) of the room label in the image. If the size line is not exactly one line below (≈1.3 × 13 px), also give `label2_px` = centre of the second line, so the overlay text sits exactly on the original.
- `size` = the size written in the room label, for the check (omit for non-rectangular rooms or rooms without a size).
- Open areas without a label (corridors, annexes of an open-plan room) still need a polygon so they get a floor: `"show_label": false`.

## openings
```json
{"id": "D1", "kind": "door|double_door|window|opening", "wall": "W5",
 "px": [228, 294],                     // from `walls` gaps: first and last gap pixel along the wall axis
 "hinge": "a|b", "swing_into": "bath1", "desc": "bath 1",
 "sill_cm": 150, "head_cm": 210, "status": "estimate"}
```
- Position: exactly one of `px` (estimate, along the wall's main axis — x for horizontal walls, y for vertical), `plan: [from,to]` (written distances from wall end `a`, plan units) or `cm: [from,to]`.
- `hinge` (single doors): the end of the opening nearer to wall end `a` or `b` — the side where the leaf line starts (the arc ends at the other jamb).
- `swing_into`: room id (or `[x,y]` plan point) of the side the door opens toward. Required for doors.
- `opening`: a passage with no door leaf. `sill_cm`/`head_cm`: per-opening heights when the user gives them.

## dims (written dimensions, exactly as on the plan)
```json
{"id": "dim12", "label": "8'", "value": 8, "a": [12,25], "b": [20,25], "label_px": [649,748],
 "status": "written|uncertain", "note": "short, ≤ 30 chars", "note_px": [x,y], "faces": "reference|outer|inner"}
```
- ids are optional (auto `dim1…`); never reuse an opening id like `D1`.
- `label` verbatim; `value` numeric in plan units (8'-6" → 8.5). `a`/`b` = the segment the number measures, on the grid. `label_px` = centre of the number in the image (the page draws the number there and the dimension line next to it).
- `uncertain` = number unreadable, or not clear which segment it belongs to. Write `note` (≤ 30 characters, shown on the drawing next to the number; move it with `note_px` if it collides) and put the full explanation in a question. An unreadable number gets `"value": null` unless a chain determines it (then put the derived value and say so). Uncertain dims always show as failing in the checks table until the user answers.
- `faces`: what the number measures to (the overlay draws it at its written length, centred on `a`–`b`, so it sits on the plan's own line). Default `reference` = the model's reference (`meta.dim_reference`). Use `outer` for an overall dimension drawn to the outside faces (e.g. 780 over a 750 centreline chain): keep `a`/`b` on the centreline grid; the check then reports the wall thickness the number implies and compares it with the thickness estimate. `inner` likewise for clear inside dimensions.
- `check` compares each dim with the geometry; a mismatch fails (shown red). Never change `value` to make it pass.

## chains (arithmetic checks on written numbers)
```json
{"name": "top chain vs overall", "terms": [8,12,11,9], "equals": 40, "tol": 0}
{"name": "top chain vs bottom chain", "terms": [8,12,11,9], "equals": [12,8,20]}
```
`equals` is a written total or another chain (list).
Add one for every chain of dimensions that should add up to an overall dimension, for opposite walls, and for room sizes stacked across the plan. Failing chains are findings, not errors to fix.
When an overall dimension is to the outer faces (`faces: "outer"`), do not also chain it against the centreline chain: the dim check already reports the implied wall thickness, and a second red row for the same question is noise.

## items (fixed elements and furniture)
Common fields: `id`, `type`, `name`, `status` (default `estimate`), `cat` (auto: fixture/furniture), `h` (cm height override).
One item per drawn piece: a sectional drawn as 5 modules = 5 `sofa_module` items (a rectangular piece is still a `sofa_module` with a 4-point poly); a straight sofa drawn as one outline = one `sofa`.
Footprint: `rect_px: [x1,y1,x2,y2]` (inclusive pixel bbox from `fp.py bbox`), or `poly_px` (for rotated/odd shapes), or `center_px` + `d_px` (round things).
Sides are plan axes: `"+x"` right, `"-x"` left, `"+y"` down, `"-y"` up.

| type | fields | default height (cm) |
|---|---|---|
| bed | `head` side, `pillows_px` (optional list of rects) | mattress 55, headboard 100 |
| table / desk | `shape: rect|round` | 75 |
| chair | `back` side, `tuck_cm` (15 when the chair is drawn at a table edge; 0 for a free chair) | seat 46, back 90 |
| sofa / armchair | `back` side, `arms` (default true) | seat 42, back 80, arms 60 |
| sofa_module | `poly_px`, `back_edge: [i,j]`, optional `arm_edge: [i,j]` (vertex indices) | 80 |
| coffee_table | `concave_cm` (inward curve of long sides) | 40 |
| tv_unit | `tv_px` rect of the screen, `front` | 50 + screen |
| wardrobe, bookshelf, dresser, nightstand | — | 220, 200, 85, 55 |
| fridge, washer | `front` | 180, 85 |
| counter | — | 90 |
| stove | `burners`, `freestanding` | on counter |
| kitchen_sink | `wall` (tap side) | on counter |
| vanity | `wall` | 85 |
| toilet | `tank` side | 78 |
| shower_tray | `wall` (shower head side) | 5 |
| bathtub | — | 55 |
| plant | `center_px`, `d_px` | ~110 |
| rug | — | 1 |
| box | `h`, `color` — anything else | 75 |

## flags (red marks that are not attached to a dim)
```json
{"text": "window symbol outside the walls — keep or ignore?", "at_px": [408,104], "box_px": [342,87,400,114]}
```
`at_px` = the **left end** of the text (it runs to the right in both languages, wrapping at ~40 characters; `note_px` on dims works the same). Every flag must have a matching entry in `questions`.

## questions / notes
Plain strings (HTML allowed: `<b>`). Questions = only what you need the user to decide; each says what you assumed meanwhile. Notes = neutral facts shown under the questions (e.g. what was treated as furniture).
