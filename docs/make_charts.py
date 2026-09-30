"""Render the README evaluation charts (light + dark variants).

    python docs/make_charts.py        # requires matplotlib

Numbers come from `python -m eval.run retrieval` (45 questions, top-6); the
hybrid rows were measured with EMBEDDING_MODEL=intfloat/multilingual-e5-large
and DENSE_RRF_WEIGHT=1.0 / 0.5. Colors are the first three categorical slots of
a CVD-validated palette (light and dark steps validated separately).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

OUT = Path(__file__).parent / "images"

CONFIGS = [  # label, Hit@1, Hit@3, MRR
    ("BM25", 0.711, 0.867, 0.795),
    ("BM25 + glossary", 0.778, 0.911, 0.855),
    ("Hybrid + glossary\n(dense weight 1.0)", 0.756, 0.956, 0.857),
    ("Hybrid + glossary\n(dense weight 0.5, default)", 0.800, 0.956, 0.880),
]
METRICS = ["Hit@1", "Hit@3", "MRR"]

LANGS = [  # label, BM25 baseline MRR, default configuration MRR
    ("English (21 q)", 0.664, 0.825),
    ("Simplified Chinese (12 q)", 0.875, 0.896),
    ("Traditional Chinese (12 q)", 0.944, 0.958),
]

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "baseline": "#898781",
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70"],
        "baseline": "#898781",
    },
}


def style_axes(ax, th):
    ax.set_facecolor(th["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(th["axis"])
    ax.tick_params(colors=th["muted"], length=0, labelsize=10)
    ax.xaxis.grid(True, color=th["grid"], linewidth=1)
    ax.set_axisbelow(True)


def rounded_bar(ax, y, width, height, color, radius_px, fig):
    """Horizontal bar: square at the baseline, 4px-rounded data end."""
    # Convert the pixel radius to data units on each axis.
    x_per_px = (ax.get_xlim()[1] - ax.get_xlim()[0]) / (ax.bbox.width)
    y_per_px = abs(ax.get_ylim()[1] - ax.get_ylim()[0]) / (ax.bbox.height)
    rx = radius_px * x_per_px
    ax.add_patch(plt.Rectangle((0, y - height / 2), max(width - rx, 0), height, color=color, linewidth=0))
    ax.add_patch(
        FancyBboxPatch(
            (max(width - 2 * rx, 0), y - height / 2),
            min(2 * rx, width),
            height,
            boxstyle=f"round,pad=0,rounding_size={rx}",
            mutation_aspect=y_per_px / x_per_px,
            color=color,
            linewidth=0,
        )
    )


def chart_configs(mode: str) -> None:
    th = THEMES[mode]
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    fig.patch.set_facecolor(th["surface"])
    style_axes(ax, th)
    ax.set_xlim(0, 1.08)
    ax.set_ylim(len(CONFIGS) - 0.45, -0.75)
    fig.canvas.draw()

    bar_h = 0.22
    gap = 0.03  # surface gap between adjacent bars
    for row, (_label, *values) in enumerate(CONFIGS):
        for j, v in enumerate(values):
            y = row + (j - 1) * (bar_h + gap)
            rounded_bar(ax, y, v, bar_h, th["series"][j], 4, fig)
            ax.text(
                v + 0.012,
                y,
                f"{v:.3f}" if METRICS[j] == "MRR" else f"{v:.0%}",
                va="center",
                fontsize=9,
                color=th["ink2"],
            )

    ax.set_yticks(range(len(CONFIGS)))
    ax.set_yticklabels([c[0] for c in CONFIGS], color=th["ink"], fontsize=10)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0", "0.25", "0.50", "0.75", "1.00"])

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in th["series"]]
    leg = ax.legend(
        handles,
        METRICS,
        loc="lower right",
        ncol=3,
        frameon=False,
        fontsize=10,
        handlelength=1.0,
        handleheight=1.0,
        bbox_to_anchor=(1.0, 1.0),
    )
    for text in leg.get_texts():
        text.set_color(th["ink2"])
    fig.text(
        0.015, 0.965, "Retrieval quality by configuration", fontsize=14, fontweight="bold", color=th["ink"], va="top"
    )
    fig.text(
        0.015,
        0.915,
        "45 questions (English, Simplified and Traditional Chinese), top-6 passages · higher is better",
        fontsize=10,
        color=th["ink2"],
        va="top",
    )
    fig.subplots_adjust(left=0.26, right=0.97, top=0.8, bottom=0.08)
    fig.savefig(OUT / f"eval-retrieval-{mode}.png", facecolor=th["surface"])
    plt.close(fig)


def chart_languages(mode: str) -> None:
    th = THEMES[mode]
    fig, ax = plt.subplots(figsize=(9, 3.4), dpi=200)
    fig.patch.set_facecolor(th["surface"])
    style_axes(ax, th)
    ax.set_xlim(0.6, 1.0)
    ax.set_ylim(len(LANGS) - 0.5, -0.6)

    for row, (_label, base, final) in enumerate(LANGS):
        ax.plot([base, final], [row, row], color=th["axis"], linewidth=2, solid_capstyle="round", zorder=1)
        ax.scatter([base], [row], s=90, color=th["baseline"], edgecolors=th["surface"], linewidths=2, zorder=2)
        ax.scatter([final], [row], s=90, color=th["series"][0], edgecolors=th["surface"], linewidths=2, zorder=3)
        ax.text(base - 0.008, row, f"{base:.3f}", ha="right", va="center", fontsize=9, color=th["ink2"])
        ax.text(
            final + 0.008, row, f"{final:.3f}", ha="left", va="center", fontsize=9, color=th["ink"], fontweight="bold"
        )

    ax.set_yticks(range(len(LANGS)))
    ax.set_yticklabels([lang[0] for lang in LANGS], color=th["ink"], fontsize=10)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", markersize=8, color=th["baseline"]),
        plt.Line2D([], [], marker="o", linestyle="", markersize=8, color=th["series"][0]),
    ]
    leg = ax.legend(
        handles,
        ["BM25 only", "Default (hybrid + glossary)"],
        loc="lower right",
        ncol=2,
        frameon=False,
        fontsize=10,
        bbox_to_anchor=(1.0, 1.0),
    )
    for text in leg.get_texts():
        text.set_color(th["ink2"])
    fig.text(0.015, 0.95, "MRR by question language", fontsize=14, fontweight="bold", color=th["ink"], va="top")
    fig.text(
        0.015,
        0.86,
        "English questions gain the most: lay wording rarely matches the brochure's terms",
        fontsize=10,
        color=th["ink2"],
        va="top",
    )
    fig.subplots_adjust(left=0.24, right=0.96, top=0.66, bottom=0.12)
    fig.savefig(OUT / f"eval-languages-{mode}.png", facecolor=th["surface"])
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for mode in THEMES:
        chart_configs(mode)
        chart_languages(mode)
    print("charts written to", OUT)
