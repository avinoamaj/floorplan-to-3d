# Reading the plan — method and pitfalls

Read this before writing model.json for the first time in a session.

## 1. What counts as "written"
- A number printed on the plan (dimension chains, room labels like `12'-0"x13'-0"`, a written wall thickness) is truth. Copy it verbatim. Never round it, never "correct" it to match the drawing, never derive it from pixels.
- Everything else (opening positions, wall thickness, furniture, fixtures) is an estimate from scale → `status: "estimate"` (orange).
- Pixel measurements serve only two purposes: (1) registration, so the overlay sits on the image; (2) estimates. If you find yourself measuring pixels to decide a written number, stop — that number is either readable (copy it) or not (flag it and ask).

## 2. Dimension reference (centreline / inside face / outside face)
Decide with evidence, then still ask:
1. Arithmetic: do chains add up to the overall dimension as written? If `8+12+11+9 = 40` exactly, the chain and the overall share one reference. If the overall is larger by roughly one wall thickness (e.g. 750 vs 780 with 30 cm walls), the overall is probably to the outside faces while the chain is to centrelines — that is a mismatch to report, not to fix.
2. `fp.py fit` `reference_test`: the reference whose x and y pixel scales agree (smallest `mismatch_pct`) is how the drawing was made.
3. Room labels: if label sizes tile the overall exactly (`6+6+13 = 25`), they are nominal / centreline sizes, not clear inside sizes. Say so in the questions.
Place the origin and wall lines on the reference you chose; record it in `meta.dim_reference`.

## 3. Attributing a dimension to a segment
- A number belongs to the segment between the two nearest wall lines (or dimension ticks) **parallel to its reading direction**, on the wall it sits next to.
- A label printed inside a room may measure a longer wall line that passes that room (e.g. "12'" inside an 8'-wide bathroom = the full wall line 0'→12'). If the room width ≠ the number, look along the same wall line for a segment with that length. If you find one, attribute it but mark `uncertain` with a note and ask. If you do not, flag and ask.
- A number you cannot read with certainty (blurred, overlapped, cut off): `uncertain`, a note such as "unreadable: 2?0", a question, and **do not** use it in geometry. If the geometry needs it and a chain determines it (overall − other terms), you may use the derived value but say so in the question.

## 4. Walls from pixels
- `fp.py info` → wall colour; `fp.py walls --rgb … -o walls.json` → every wall line with centre, thickness and gaps.
- A gap is an opening (door, window, passage) **or** simply a place with no wall. Look at a crop (`fp.py crop`) when in doubt: door = jambs + leaf line + arc; window = thin parallel lines across the wall; passage = nothing.
- Map each wall line to the grid coordinate implied by the written dimensions (e.g. line V2 at x = 8'). Build `pairs.json` from those ids and run `fp.py fit`. Residual > 1.5 px means a wrong mapping or a wrong reference — fix before going on.
- Thickness: if written numbers imply it (overall to outer faces − centreline chain = one outer wall), use that value with status `derived`. Otherwise use `thickness_estimate_cm` from `fit` (median band thickness / s, rounded half-up), status `estimate`. Report both in the questions.
- A long gap in a `walls` line where nothing is drawn (no jambs, no symbol) means there is no wall there: end the wall at each side (two walls), and give the open area a room polygon. Do not model it as an `opening`.

## 5. Openings
- Use the gap pixels from `walls` directly as `px: [first, last]`. They include the jamb blocks; that is the rough opening.
- Door hinge: the leaf line (the straight line from the wall, drawn open at 90°) starts at the hinge; the arc runs from the leaf tip to the other jamb. `hinge` = the end of the opening nearer to wall end `a` or `b`.
- `swing_into` = the room on the side of the leaf/arc.
- Double door: two leaves, two arcs meeting in the middle → `double_door`. Sliding doors / openings with no leaf → `opening`.

## 6. Furniture and fixtures
- Include everything drawn (beds, sofas, tables, chairs, TV units, plants, rugs) unless the user says otherwise. Fixed elements: counters, hobs, sinks, toilets, showers, baths.
- Get footprints with `fp.py bbox --region …` (dark outlines) or `--mode green` (plants). Make the region a few px larger than the object and keep walls and text out of it. `full_cols`/`full_rows` reveal headboards, backs, folds. When pieces touch (table + chairs), `--components` lists each separate outline; when they merge, read the split from `full_cols`/`full_rows` or one enlarged crop.
- Copy script numbers as they are; if you must read a value off a crop, say so in a note.
- For angled pieces (sectional sofas, rotated armchairs), read the corner pixels from an enlarged crop and use `poly_px`.
- Chairs drawn partly outside a table: use the drawn rect plus `tuck_cm` for the part hidden under the table.

## 7. Red flags (always look for)
- Chains that do not add up; opposite sides that disagree; a room label that does not fit its walls.
- A dimension that cannot be tied to one segment; unreadable digits.
- Symbols outside the building or not touching any wall; walls that end in the air; doors whose arc hits a wall or fixture.
- Scale drift: x and y scales disagreeing by more than ~1% (`anisotropy_pct`) → the image may be stretched; ask.

## 8. Writing the questions
- Mixed Hebrew + numbers: the pages wrap each run of numbers/operators in a bidi isolate, so "400 + 350 = 750" or "260 / 210 / 90 / 210" keeps its order. Still prefer a short sentence over a formula, and look at the questions once in the `--full` screenshot.
- Only questions whose answer changes the model. Each one: what you saw, what you assumed meanwhile, what you need. Number them.
- Always include (unless the user already answered): dimension reference, wall thicknesses (if estimated), and heights for stage 2 (ceiling, door head, window sill/head) stating the defaults 260/210/90/210 that will apply if unanswered.
- A plan with no written overall dimension: check opposite sides against each other with chains instead.
- Do not ask about things the plan states.

## 9. Page pitfalls (already handled by the templates — don't hand-edit pages)
- RTL documents push absolutely positioned CSS2D labels off-screen → the label layer is forced LTR.
- CSS2DRenderer ignores a hidden parent's visibility and does not depth-test → labels are hidden by script (parent chain + raycast occlusion).
- `fp.py build2` refuses to run when model.json changed after `approve`, so stage 2 always uses exactly the approved stage-1 data.
