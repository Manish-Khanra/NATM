"""Observed-fleet dataset construction figure for the paper (monochrome schematic).

Shows HOW the per-asset aviation and maritime baseline datasets are built from
raw open records: flight / port-call information, distance, the fuel-burn and
energy calculation, and aggregation to per-asset annual activity + energy.
Each step box carries a short description and, below a light rule, its key
calculation. Renders analysis/outputs/fig_fleet_dataset_construction.{pdf,png}.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

BLACK = "#1a1a1a"; GREY = "#555555"; HAIR = "#bdbdbd"
plt.rcParams.update({"font.family": "DejaVu Sans", "savefig.dpi": 400,
                     "savefig.bbox": "tight", "pdf.fonttype": 42, "ps.fonttype": 42})

fig, ax = plt.subplots(figsize=(11.2, 13.2))
ax.set_xlim(0, 100); ax.set_ylim(0, 128); ax.axis("off")

# ---- geometry ----
colL, colR = 3, 53          # box left-x
BW = 44                     # box width
BH = 13.6                    # box height
PITCH = 15.2
TOP = 108.0                 # bottom-y of first row
rows_y = [TOP - i*PITCH for i in range(7)]
DS_H = 10.4

def step(x, y, title, desc, formula=""):
    ax.add_patch(Rectangle((x, y), BW, BH, fill=False, edgecolor=BLACK, linewidth=0.8, zorder=2))
    ax.text(x+3.4, y+BH-2.7, title, ha="left", va="top", fontsize=10.5, color=BLACK,
            fontweight="bold", zorder=3)
    ax.text(x+3.4, y+BH-7.2, desc, ha="left", va="top", fontsize=8.4, color=GREY, zorder=3)
    if formula:
        ax.plot([x+3.4, x+BW-3.4], [y+4.6, y+4.6], color=HAIR, lw=0.5, zorder=2)  # divider
        ax.text(x+3.4, y+2.2, formula, ha="left", va="center", fontsize=8.6, color=BLACK,
                style="italic", zorder=3)

def varrow(x, y_top, y_bot):
    ax.add_patch(FancyArrowPatch((x, y_top), (x, y_bot), arrowstyle="-|>", mutation_scale=10,
                 lw=0.9, color=BLACK, shrinkA=0, shrinkB=0, zorder=1))

# ---- column headers ----
ax.text(colL+BW/2, 123.5, "OBSERVED  AVIATION  FLEET", ha="center", va="bottom",
        fontsize=10.6, color=BLACK, fontweight="bold")
ax.text(colR+BW/2, 123.5, "OBSERVED  MARITIME  FLEET", ha="center", va="bottom",
        fontsize=10.6, color=BLACK, fontweight="bold")
ax.plot([colL, colL+BW], [122.2, 122.2], color=HAIR, lw=0.6)
ax.plot([colR, colR+BW], [122.2, 122.2], color=HAIR, lw=0.6)

# ================= AVIATION =================
AV = [
 ("Flight records", "OpenSky /flights/all", "496,778 flights  ·  icao24, airports, times"),
 ("Route distance", "from airport coordinates", "d  =  great-circle  (R = 6371 km)"),
 ("Classify activity", "domestic vs international; haul", "short < 1500 < medium < 4000 < long  (km)"),
 ("Mission profile", "OpenAP climb · cruise · descent", "altitude & speed by distance, steps Δt"),
 ("Fuel burn", "integrate along the profile", "fuel  =  Σ  ff · Δt   (mass updated)"),
 ("Energy & emissions", "per flight, from fuel burnt", "E = fuel · 43 / 3600 ;   CO₂ = 3.16 · fuel"),
 ("Per-aircraft profile", "aggregate each aircraft's flights", "flights, distance, stage length, Σ energy"),
]
# ================= MARITIME =================
MA = [
 ("MRV emission reports", "audited annual fuel & CO₂", "i  =  fuel per n mile   (intensity)"),
 ("Port-call records", "Global Fishing Watch AIS 2024", "dated port visits per vessel"),
 ("Build voyages", "chain consecutive port visits", "legs  →  voyages / year"),
 ("Sea-route distance", "searoute per leg; sum over year", "annual distance  (n mile)"),
 ("Annual fuel", "MRV total, else distance × i", "fuel  =  Σ  i · leg distance"),
 ("Energy intensity", "fuel intensity → energy", "E-int  =  i · LHV / 3600   (MWh/n mile)"),
 ("Per-vessel profile", "aggregate per vessel", "voyages, distance, fuel, energy, hub"),
]
for (t, d, f), y in zip(AV, rows_y): step(colL, y, t, d, f)
for (t, d, f), y in zip(MA, rows_y): step(colR, y, t, d, f)
for i in range(len(rows_y)-1):
    varrow(colL+BW/2, rows_y[i], rows_y[i+1]+BH)
    varrow(colR+BW/2, rows_y[i], rows_y[i+1]+BH)

# ================= dataset banners =================
ds_y = rows_y[-1] - PITCH + (BH - DS_H)
def dataset(x, label):
    ax.add_patch(Rectangle((x, ds_y), BW, DS_H, fill=False, edgecolor=BLACK, linewidth=1.3, zorder=2))
    ax.text(x+BW/2, ds_y+DS_H/2, label, ha="center", va="center", fontsize=8.6, color=BLACK,
            fontweight="bold", linespacing=1.4)
dataset(colL, "Aviation fleet dataset\n474 passenger + 74 freight aircraft\nactivity & energy per aircraft")
dataset(colR, "Maritime fleet dataset\n131 cargo vessels\nactivity & energy per vessel")
varrow(colL+BW/2, rows_y[-1], ds_y+DS_H)
varrow(colR+BW/2, rows_y[-1], ds_y+DS_H)

fig.savefig("analysis/outputs/fig_fleet_dataset_construction.png")
fig.savefig("analysis/outputs/fig_fleet_dataset_construction.pdf")
print("written")
