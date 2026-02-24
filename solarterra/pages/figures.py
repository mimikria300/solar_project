import plotly.graph_objects as go
from plotly.subplots import make_subplots


def scatter(plot):

    if len(plot.y_arrays) == 0 or len(plot.y_arrays[0]) == 0:
        return "<div>No significant data for this period.</div>"

    fig = go.Figure()

    x, y = plot.get_values(0)

    fig.add_trace(go.Scatter(
        x=x, y=y, connectgaps=False, mode="lines+markers"))

    fig.update_traces(connectgaps=False, marker=dict(size=4))
    fig.update_layout(
        xaxis_range=[plot.t_start, plot.t_stop],
        yaxis_title=plot.variable.get_axis_label(),
    )


    fig.update_yaxes(type=plot.variable.scaletyp)

    config = {'displayModeBar': False}

    plot_div = fig.to_html(config=config, full_html=False,
                           div_id=f"plot_div_{plot.variable.id}", default_width="100%")
    return plot_div


def n_trace(plot):

    fields = plot.y_fields
    
    if len(plot.y_arrays) == 0:
        return "<div>No significant data for this period.</div>"

    fig = make_subplots(rows=len(fields), cols=1,
                        shared_xaxes=True, vertical_spacing=0.05)
    for index, field in enumerate(fields):
        x, y = plot.get_values(index)
        fig.add_trace(go.Scatter(
            x=plot.x_field_array,
            y=plot.y_arrays[index],
            connectgaps=False,
            mode="lines+markers",
        ),
            row=index + 1,
            col=1
        )
        fig['layout'][f"yaxis{index+1}"]['title'] = plot.variable.get_axis_label(index)
        fig['layout'][f"xaxis{index+1}"]['range'] = [plot.t_start, plot.t_stop]

    fig.update_traces(marker=dict(size=4))
    

    fig.update_layout(
        height=700,
        #xaxis_range=[ts[0], ts[1]],
        showlegend=False,
    )

    config = {'displayModeBar': False}
    plot_div = fig.to_html(config=config, full_html=False,
                           div_id=f"plot_div_{plot.variable.id}", default_width="100%")

    return plot_div
