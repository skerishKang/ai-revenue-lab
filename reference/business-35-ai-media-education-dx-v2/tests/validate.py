#!/usr/bin/env python3
"""Static validation for Business 35 v2 (파디엠 AI 미디어 업무전환)."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
errors = []
checks = []

def check(name, ok, detail=""):
    checks.append((name, bool(ok)))
    if not ok:
        errors.append(f"{name}: {detail}")

def text(rel):
    return (ROOT / rel).read_text(encoding="utf-8") if (ROOT / rel).is_file() else ""

RUNTIME = ["index.html", "styles/main.css", "scripts/data.js", "scripts/app.js"]
RT = "\n".join(text(f) for f in RUNTIME)

# required files
for f in ["index.html", "styles/main.css", "scripts/data.js", "scripts/app.js",
          "README.md", "PRODUCT_CONTRACT.md", "REFERENCE_BOARD.md", "REFERENCE_ADOPTION_MAP.md",
          "VISUAL_DIRECTION.md", "MOTION_SPEC.md", "IMAGE_SOURCES.md", "ASSET_ART_DIRECTION.md"]:
    check(f"required file exists: {f}", (ROOT / f).is_file())

html = text("index.html")

# 8 product sections
for sec in ["hero", "thesis", "diagnostic", "case", "workflow", "offers", "deliverables", "conversion"]:
    check(f"section present: #{sec}", f'id="{sec}"' in html)

# provider identity + boundaries
check("provider 파디엠 present", "파디엠" in html)
check("provider PADIEM present", "PADIEM" in html)
check("no 'AI Revenue Lab' as customer-facing provider", "AI Revenue Lab" not in RT)
check("price hypothesis noted", "시장 검증 전 가설" in RT)
check("synthetic case noted", "합성 사례" in RT)
check("no auto-publish claim", "자동 게시" in html or "사람 검토" in html)

# no external runtime requests (http/https URLs in runtime files)
for f in RUNTIME:
    c = text(f)
    m = c.replace("https://", "").replace("http://", "")
    if c != m:
        check(f"no external URL in {f}", False, "found http/https")
check("no external URL in runtime (aggregate)", all("http://" not in text(f) and "https://" not in text(f) for f in RUNTIME))

# image assets exist
for img in ["hero-studio.jpg","hero-office.jpg","workshop-meeting.jpg","studio-design.jpg","media-team.jpg",
            "creative-collab.jpg","presentation.jpg","review-desk.jpg","strategy-map.jpg","video-production.jpg",
            "camera-media.jpg","workspace-laptop.jpg"]:
    check(f"image exists: {img}", (ROOT / "assets/images" / img).is_file())

# JS syntax
for f in ["scripts/data.js", "scripts/app.js"]:
    r = subprocess.run(["node", "--check", str(ROOT / f)], capture_output=True, text=True)
    check(f"JS syntax: {f}", r.returncode == 0, r.stderr)

# deterministic diagnostic data present
check("diagnostic logic present", "diag(" in text("scripts/data.js"))
check("offers A/B1/B2/C present", all(x in html for x in ["A · 진단 워크숍", "B1 · 디자인", "B2 · 표준 6주", "C · 운영 자문"]))
check("deliverable mockups present", "data-del" in html)
check("conversion options present", all(x in html for x in ["진단 상담", "적용 시나리오", "파일럿 제안"]))

# 390px/tablet/desktop responsive + reduced motion
css = text("styles/main.css")
check("mobile media query", "@media (max-width: 760px)" in css or "@media (max-width: 1024px)" in css)
check("reduced motion", "prefers-reduced-motion" in css)

print(json.dumps({"status": "pass" if not errors else "fail", "checks_total": len(checks),
                  "checks_passed": sum(1 for _, ok in checks if ok), "checks_failed": len(errors),
                  "errors": errors}, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)
