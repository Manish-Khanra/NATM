"""Data-preparation pipeline figure for the paper — monochrome journal schematic.

Renders analysis/outputs/fig_data_preparation_pipeline.{pdf,png} (vector PDF is
the paper asset). Black-and-white, hairline rules, no fills, minimal text; the
Ariadne-pathway row is dashed to mark it as scenario (not observed) data.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

BLACK = "#1a1a1a"; GREY = "#5a5a5a"; LIGHT = "#8a8a8a"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "savefig.dpi": 400, "savefig.bbox": "tight",
    "pdf.fonttype": 42, "ps.fonttype": 42,
})

fig, ax = plt.subplots(figsize=(12.4, 5.4))
ax.set_xlim(0, 130); ax.set_ylim(0, 57); ax.axis("off"); ax.set_aspect("auto")

# ---- geometry ----
col_x = [16, 35.5, 55, 74.5, 94]        # box left-x per stage
BW, BH = 17, 11.5                        # box width / height
row_y = {"av": 40, "ma": 25, "pa": 10}   # box bottom-y per track
HEADERS = ["Sources", "Filter", "Map / match", "Derive", "Calibrate"]

def cell(x, y, main, sub="", dashed=False):
    ax.add_patch(Rectangle((x, y), BW, BH, fill=False, edgecolor=BLACK,
                 linewidth=0.8, linestyle=(0, (4, 2)) if dashed else "solid", zorder=2))
    if sub:
        ax.text(x+BW/2, y+BH-2.4, main, ha="center", va="top", fontsize=8.3, color=BLACK, zorder=3)
        ax.text(x+BW/2, y+BH-5.6, sub, ha="center", va="top", fontsize=7.0, color=GREY,
                zorder=3, linespacing=1.3)
    else:
        ax.text(x+BW/2, y+BH/2, main, ha="center", va="center", fontsize=8.3, color=BLACK,
                zorder=3, linespacing=1.3)

def harrow(x1, x2, y, dashed=False):
    ax.add_patch(FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>", mutation_scale=9,
                 lw=0.8, color=BLACK, linestyle=(0, (4, 2)) if dashed else "solid",
                 shrinkA=0, shrinkB=0, zorder=1))

# ---- column headers + hairline underline ----
for x, h in zip(col_x, HEADERS):
    ax.text(x+BW/2, 53.6, h.upper(), ha="center", va="bottom", fontsize=8.2,
            color=LIGHT, fontweight="bold")
ax.plot([col_x[0], col_x[-1]+BW], [52.7, 52.7], color=LIGHT, lw=0.5, zorder=1)

# ---- row labels (left, small caps) ----
for key, lab in [("av", "AVIATION"), ("ma", "MARITIME"), ("pa", "PATHWAYS")]:
    ax.text(14.5, row_y[key]+BH/2, lab, ha="right", va="center", fontsize=8.2,
            color=BLACK, fontweight="bold", rotation=0)

# ================= AVIATION =================
y = row_y["av"]
cell(col_x[0], y, "Observed aviation", "Planespotters · OpenSky ·\nOpenAP · ICAO/EASA EDB")
cell(col_x[1], y, "German carriers", "474 passenger +\n74 freight aircraft")
cell(col_x[2], y, "Identity", "reg → ICAO24;\ntype → OpenAP")
cell(col_x[3], y, "Flight energy", "fuel & emissions per\nflight, then per aircraft")
cell(col_x[4], y, "Technology catalog", "CAPEX, emission\nfactors, km/kWh")

# ================= MARITIME =================
y = row_y["ma"]
cell(col_x[0], y, "Observed maritime", "EU MRV · Global Fishing\nWatch · IMO · searoute")
cell(col_x[1], y, "German vessels", "131 cargo vessels\n(gross-tonnage rule)")
cell(col_x[2], y, "Identity", "IMO join;\nMRV intensity")
cell(col_x[3], y, "Voyage energy", "port calls → legs;\nfuel per leg")
cell(col_x[4], y, "Technology catalog", "CAPEX, emission\nfactors, km/kWh")

# ================= PATHWAYS (dashed = scenario, not observed) =================
y = row_y["pa"]
cell(col_x[0], y, "Ariadne pathways", "six transition\npathways", dashed=True)
cell(col_x[1], y, "Milestone years", "2030 · 35 · 40 · 45", dashed=True)
cell(col_x[2], y, "Carrier prices", "forecast columns →\nper-carrier prices", dashed=True)
cell(col_x[3], y, "Weighted price", "activity-weighted\nelectricity", dashed=True)
cell(col_x[4], y, "Demand", "index × 2025\nanchor", dashed=True)

# ---- intra-row arrows ----
for key in ("av", "ma", "pa"):
    yy = row_y[key] + BH/2
    for i in range(4):
        harrow(col_x[i]+BW, col_x[i+1], yy, dashed=(key == "pa"))

# ---- "determines" notes (plain italic, left-aligned, under each row) ----
notes = {"av": "→ 2025 fleet, per-asset activity & energy, emission factors",
         "ma": "→ 2025 vessel stock & identity, per-vessel activity & energy",
         "pa": "→ scenario prices, demand trajectories, belief probabilities"}
for key, txt in notes.items():
    ax.text(col_x[0], row_y[key]-1.4, txt, ha="left", va="top", fontsize=6.8,
            style="italic", color=LIGHT)

# ---- convergence to case inputs ----
cx, pw = col_x[4] + BW + 5, 13
panel_y, panel_h = row_y["pa"], row_y["av"] + BH - row_y["pa"]
ax.add_patch(Rectangle((cx, panel_y), pw, panel_h, fill=False, edgecolor=BLACK, linewidth=0.9, zorder=2))
ax.text(cx+pw/2, panel_y+panel_h-3, "24 case\ninputs", ha="center", va="top", fontsize=8.6,
        color=BLACK, linespacing=1.25)
ax.text(cx+pw/2, panel_y+panel_h/2-2, "3 sectors\n× 8 cases", ha="center", va="center",
        fontsize=7.2, color=GREY, linespacing=1.3)
for key in ("av", "ma", "pa"):
    yy = row_y[key] + BH/2
    harrow(col_x[4]+BW, cx, yy, dashed=(key == "pa"))

# ---- downstream model (single thin box spanning full width) ----
mx, my, mh = col_x[0], 0, 4.4
mw = cx + pw - mx
ax.add_patch(FancyArrowPatch((cx+pw/2, panel_y), (cx+pw/2, my+mh), arrowstyle="-|>",
             mutation_scale=9, lw=0.8, color=BLACK, shrinkA=1, shrinkB=1, zorder=1))
ax.add_patch(Rectangle((mx, my), mw, mh, fill=False, edgecolor=BLACK, linewidth=0.9, zorder=2))
ax.text(mx+mw/2, my+mh/2, "NATM agent-based investment model, 2025–2050     "
        "→     technology per asset-year · energy & CO₂ by carrier · electricity-equivalent demand",
        ha="center", va="center", fontsize=7.6, color=BLACK)

fig.savefig("analysis/outputs/fig_data_preparation_pipeline.png")
fig.savefig("analysis/outputs/fig_data_preparation_pipeline.pdf")
print("written")
