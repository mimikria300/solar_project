import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np


PLOT_HEIGHT = 250
PLOT_MARGIN = dict(l=80, r=80, t=0, b=20)
AXIS_COLOR = "black"
AXIS_LINE_WIDTH = 2
MAJOR_TICK_LEN = 8
MAJOR_TICK_WIDTH = 2
MINOR_TICK_LEN = 4
MINOR_TICK_WIDTH = 2 
GRID_WIDTH = 2
GRID_COLOR = "rgba(0, 0, 0, 0.15)"
FONT_SIZE = 14


def apply_common_layout(fig, height):
    fig.update_layout(
        height=height,               # высота
        margin=PLOT_MARGIN,          # отступы
        autosize=True,               # пересчет размера
        showlegend=False,            # легенда
        plot_bgcolor="white",        # внутри осей
        paper_bgcolor="white",       # вне осей
    )


def apply_axis_style(fig):
    common_axis_kwargs = dict(
        showline=True,               # ось
        linecolor=AXIS_COLOR,        # цвет оси
        linewidth=AXIS_LINE_WIDTH,   # толщина оси
        ticks="inside",              # тики внутрь
        tickcolor=AXIS_COLOR,        # цвет тиков
        ticklen=MAJOR_TICK_LEN,      # длина тиков
        tickwidth=MAJOR_TICK_WIDTH,  # толщина тиков
        tickfont=dict(               # подписи тиков
            size=FONT_SIZE,
            color=AXIS_COLOR,
        ),
        title_font=dict(             # подпись осей
            size=FONT_SIZE,
            color=AXIS_COLOR,
        ),
        showgrid=True,               # сетка
        gridcolor=GRID_COLOR,        # цвет сетки
        gridwidth=GRID_WIDTH,        # толщина сетки
        zeroline=False,              # нулевая линия
    )

    # короткие тики
    minor_axis_kwargs = dict(
        ticks="inside",
        ticklen=MINOR_TICK_LEN,
        tickwidth=MINOR_TICK_WIDTH,
        tickcolor=AXIS_COLOR,
        showgrid=False,
    )

    fig.update_xaxes(
        **common_axis_kwargs,
        minor=minor_axis_kwargs,
    )

    fig.update_yaxes(
        **common_axis_kwargs,
        minor=minor_axis_kwargs,
    )


def scatter(plot):

    if len(plot.y_arrays) == 0 or len(plot.y_arrays[0]) == 0:
        return '<div class="no_data">No significant data for this period.</div>'

    fig = go.Figure()

    x, y = plot.get_values(0)

    fig.add_trace(go.Scatter(
        x=x, y=y, connectgaps=False, mode="lines+markers"))

    fig.update_traces(connectgaps=False, marker=dict(size=4))

    apply_common_layout(fig, PLOT_HEIGHT)
    apply_axis_style(fig)

    fig.update_xaxes(
        range=[plot.t_start, plot.t_stop],
        title_text='Time, UT',
    )

    fig.update_yaxes(
        title_text=plot.variable.get_axis_label(),
        type=plot.variable.scaletyp,
        automargin=False,
    )

    config = {'displayModeBar': False}

    plot_div = fig.to_html(config=config, full_html=False,
                           div_id=f"plot_div_{plot.variable.id}", default_width="100%")
    return plot_div


def n_trace(plot):

    fields = plot.y_fields
    
    if len(plot.y_arrays) == 0:
        return '<div class="no_data">No significant data for this period.</div>'

    fig = make_subplots(rows=len(fields), cols=1,
                        shared_xaxes=True, vertical_spacing=0.05)
    for index, field in enumerate(fields):
        x, y = plot.get_values(index)
        fig.add_trace(go.Scatter(
            x=x,
            y=y,
            connectgaps=False,
            mode="lines+markers",
        ),
            row=index + 1,
            col=1
        )
        fig.update_yaxes(
            title_text=plot.variable.get_axis_label(index),
            row=index + 1,
            col=1,
        )

    fig.update_traces(marker=dict(size=4))
    
    apply_common_layout(fig, PLOT_HEIGHT * len(fields) - 70)
    apply_axis_style(fig)

    fig.update_xaxes(
        range=[plot.t_start, plot.t_stop],
    )

    fig.update_xaxes(
        title_text='Time, UT',
        row=len(fields),
        col=1,
    )

    fig.update_yaxes(
        automargin=False,
    )

    config = {'displayModeBar': False}
    plot_div = fig.to_html(config=config, full_html=False,
                           div_id=f"plot_div_{plot.variable.id}", default_width="100%")

    return plot_div


def spectrogram(plot):
    if plot.z_matrix is None or plot.z_matrix.size == 0:
        return '<div class="no_data">No significant data for this period.</div>'

    if np.all(np.isnan(plot.z_matrix)):
        return '<div class="no_data">No significant data for this period (all values are NaN).</div>'

    z_data = plot.z_matrix.T.copy()

    data_scaletyp = getattr(plot.variable, 'scaletyp', None)

    try:
        axis_label = plot.variable.get_axis_label()
    except Exception:
        axis_label = None

    if not axis_label:
        axis_label = plot.variable.name

    if data_scaletyp == 'log':
        with np.errstate(divide='ignore', invalid='ignore'):
            z_data = np.log10(z_data)
        z_data[~np.isfinite(z_data)] = np.nan
        colorbar_title = f"log₁₀({axis_label})"
    else:
        colorbar_title = axis_label

    fig = go.Figure()

    fig.add_trace(go.Heatmap(
        x=plot.x_axis,
        y=plot.y_axis,
        z=z_data,
        colorscale='Jet',
        colorbar=dict(
            title=dict(
                text=colorbar_title,
                side='right',
                font=dict(
                    size=FONT_SIZE,
                    color=AXIS_COLOR,
                ),
            ),
            tickfont=dict(
                size=FONT_SIZE,
                color=AXIS_COLOR,
            ),
            x=1.0,
            xanchor='left',
            xpad=10,
            thicknessmode="pixels",
            thickness=15,
            lenmode="fraction",
            len=1.0,
        ),
        hoverongaps=False,
    ))

    apply_common_layout(fig, PLOT_HEIGHT)
    apply_axis_style(fig)

    fig.update_xaxes(
        range=[plot.t_start, plot.t_stop],
        title_text='Time, UT',
    )

    fig.update_yaxes(
        title_text=plot.y_axis_label,
        automargin=False,
    )

    if plot.y_scaletyp == 'log':
        fig.update_yaxes(type='log')

    config = {'displayModeBar': False}
    plot_div = fig.to_html(
        config=config,
        full_html=False,
        div_id=f"plot_div_{plot.variable.id}",
        default_width="100%"
    )
    return plot_div
