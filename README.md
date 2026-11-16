# floorplan-to-3d

A Claude skill that turns a floor-plan image (with written dimensions) into:

1. **Stage 1 – a 2D verification overlay**: the original plan in the background, a transparent SVG drawing on top in the same scale, colour-coded (black = written dimension, orange = estimated from scale, red = uncertain / failed check), a checks table and the open questions. The work stops here for approval.
2. **Stage 2 – an interactive Three.js model** built from exactly the approved data: walls with real door/window openings, floors, a ceiling you can hide, furniture and fixtures, orbit / top / first-person walk (160 cm eye height), a click-two-points measuring tool with snapping, and dimension lines.

All geometry lives in one `model.json`. Every page is generated from it by `scripts/fp.py`, and stage 2 refuses to build if the model changed after approval (sha256). The same model always produces the same pages.

```
SKILL.md                  instructions Claude follows
scripts/fp.py             probe (info, walls, scan, bbox, crop, fit) + check, build1, approve, build2, shoot
assets/stage1.html        overlay template
assets/stage2.html        3D template (three.js 0.160.0 from jsDelivr)
references/model_schema.md   model.json fields, furniture catalogue
references/method.md      how to read a plan; pitfalls
evals/                    test cases for the skill itself
```

Requirements: Python 3 with Pillow and NumPy (SciPy recommended). Playwright + Chrome are optional, used for screenshots.

Versions are pinned by git tag. The skill clones `v1`.
