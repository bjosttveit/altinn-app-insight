from typing import cast

import matplotlib.pyplot as plt
from ipympl.backend_nbagg import Canvas


def setup_plot(title: str | None = None):
    fig, ax = plt.subplots()
    fig.autofmt_xdate()
    canvas = cast(Canvas, fig.canvas)
    canvas.header_visible = False
    canvas.capture_scroll = False
    if title is not None:
        fig.suptitle(title)
    return fig, ax
