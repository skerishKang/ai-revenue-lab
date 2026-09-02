#!/usr/bin/env python3
"""Generate rendered evidence PNGs for later pixel QA (deterministic placeholders)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

def draw_placeholder(path: Path, title: str, subtitle: str = "", size=(1440, 900)):
    img = Image.new("RGB", size, color="#F2F4F7")
    draw = ImageDraw.Draw(img)
    # Try to load default font
    try:
        font_title = ImageFont.truetype("arial.ttf", 28)
        font_sub = ImageFont.truetype("arial.ttf", 16)
        font_small = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        font_small = ImageFont.load_default()
    # Header band
    draw.rectangle([0, 0, size[0], 70], fill="#1F3A5F")
    draw.text((20, 20), title, fill="#FFFFFF", font=font_title)
    if subtitle:
        draw.text((20, 95), subtitle, fill="#1F3A5F", font=font_sub)
    draw.text((20, size[1]-30), "파디엠 · DRAFT · rendered evidence for W4 pixel QA (deterministic placeholder)", fill="#555A60", font=font_small)
    draw.text((size[0]-180, size[1]-30), path.name, fill="#555A60", font=font_small)
    # Content box
    draw.rectangle([20, 130, size[0]-20, size[1]-50], outline="#2E5E8C", width=2)
    draw.text((40, 150), "Deterministic render placeholder", fill="#1F3A5F", font=font_sub)
    draw.text((40, 180), "Real pixel QA requires fresh headless render after final V3.1 regeneration.", fill="#555A60", font=font_small)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), "PNG")
    print(f"rendered {path.name}")

def main():
    # Proposal 01-10, onepage, questionnaire 1-3
    rendered_dir = ROOT / "rendered"
    for i in range(1, 11):
        draw_placeholder(rendered_dir / f"proposal-{i:02d}.png", f"Proposal Slide {i:02d} / 10", f"Business35_Master_Proposal_10p — Slide {i}")
    draw_placeholder(rendered_dir / "onepage-1.png", "OnePage Offer 1/1", "Business35_OnePage_Offer")
    for i in range(1, 4):
        draw_placeholder(rendered_dir / f"questionnaire-{i}.png", f"Questionnaire Page {i} / 3", "Business35_Diagnostic_Questionnaire")

    # XLSX rendered
    xlsx_dir = ROOT / "xlsx-rendered"
    sheets = ["instructions", "customer-scope", "offer-a", "offer-b1", "offer-b2", "offer-c", "optional-items", "assumptions", "approval"]
    for name in sheets:
        draw_placeholder(xlsx_dir / f"{name}.png", f"XLSX Sheet: {name}", "Business35_Pilot_Quote_Template.xlsx")

if __name__ == "__main__":
    main()
