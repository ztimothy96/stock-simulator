import datetime
import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
import streamlit as st


def get_inputs():
    st.sidebar.header("Input Parameters")

    name = st.sidebar.text_input("Company Name", "Company")

    # Shares & projection horizon
    shares_outstanding = st.sidebar.number_input("Outstanding Shares",
                                                 min_value=1_000_000,
                                                 step=1_000_000,
                                                 value=100_000_000)
    years = st.sidebar.slider("Projection Years", 1, 10, 5)

    # Revenue streams
    rev_streams = st.sidebar.text_area("Revenue Streams (comma separated)",
                                       "Product A, Product B").split(',')
    rev_streams = [r.strip() for r in rev_streams if r.strip()]

    # Current financials
    rev_per_stream = {stream: 0 for stream in rev_streams}
    for stream in rev_streams:
        rev_per_stream[stream] = st.sidebar.number_input(
            f"{stream} Revenue ($M)", min_value=10, step=10, value=1000)

    current_revenue = sum(rev_per_stream.values())
    current_margin = st.sidebar.slider("Current Operating Margin (%)", 0, 100,
                                       20) / 100
    st.sidebar.markdown(
        f"**Current Total Revenue ($M): {current_revenue:.2f}**")
    st.sidebar.markdown(
        f"**Current Operating Income ($M): {current_revenue * current_margin:.2f}**"
    )

    # Growth assumptions
    st.sidebar.subheader("Growth & Margins")
    growth_inputs = {}
    for stream in rev_streams:
        st.sidebar.markdown(f"**{stream}**")
        bear = st.sidebar.number_input(
            f"{stream} Bear Growth %", -50, 100, 5, key=f"{stream}_bear") / 100
        base = st.sidebar.number_input(
            f"{stream} Base Growth %", -50, 100, 10,
            key=f"{stream}_base") / 100
        bull = st.sidebar.number_input(
            f"{stream} Bull Growth %", -50, 100, 20,
            key=f"{stream}_bull") / 100
        growth_inputs[stream] = {"bear": bear, "base": base, "bull": bull}

    # Margin assumptions
    bear = st.sidebar.slider("Bear Case Margin (%)", 0, 100, 15) / 100
    base = st.sidebar.slider("Base Case Margin (%)", 0, 100, 20) / 100
    bull = st.sidebar.slider("Bull Case Margin (%)", 0, 100, 25) / 100
    final_margins = {"bear": bear, "base": base, "bull": bull}
    return name, shares_outstanding, years, rev_streams, rev_per_stream, current_revenue, current_margin, growth_inputs, final_margins


def run_projections(scenarios, years, shares_outstanding, current_revenue,
                    current_margin, rev_per_stream, growth_inputs,
                    final_margins):

    revenues = {s: np.zeros(years + 1) for s in scenarios}
    net_income = {s: np.zeros(years + 1) for s in scenarios}
    eps = {s: np.zeros(years + 1) for s in scenarios}

    for scenario in scenarios:
        # Revenue projections
        total_rev = np.zeros(years + 1)
        total_rev[0] = current_revenue
        for year in range(1, years + 1):
            year_rev = 0
            for stream, base_val in rev_per_stream.items():
                g = growth_inputs[stream][scenario]
                stream_rev = base_val * ((1 + g)**year)
                year_rev += stream_rev
            total_rev[year] = year_rev
        revenues[scenario] = total_rev

        # Margin interpolation
        final_margin = final_margins[scenario]
        margins = np.linspace(current_margin, final_margin, years + 1)

        # Net income & EPS
        ni = total_rev * margins
        net_income[scenario] = ni
        eps[scenario] = (
            ni * 1e6
        ) / shares_outstanding  # revenue in $M → convert to $ before EPS

    return revenues, net_income, eps


def main():
    scenarios = ["bear", "base", "bull"]
    # Define consistent colors for all charts
    colors_map = {
        'bear': '#d62728',  # Red for bear case
        'base': '#1f77b4',  # Blue for base case  
        'bull': '#2ca02c'  # Green for bull case
    }

    (name, shares_outstanding, years, rev_streams, rev_per_stream,
     current_revenue, current_margin, growth_inputs,
     final_margins) = get_inputs()

    st.title(f"📈 {name} Stock Projection")
    revenues, net_income, eps = run_projections(scenarios, years,
                                                shares_outstanding,
                                                current_revenue,
                                                current_margin, rev_per_stream,
                                                growth_inputs, final_margins)

    st.subheader("Net Income & EPS Projections")
    start_year = datetime.datetime.now().year
    years_range = list(range(start_year, start_year + years + 1))
    revenue_fig = _make_revenue_plot(scenarios, colors_map, years_range,
                                     revenues)
    net_income_fig = _make_net_income_plot(scenarios, colors_map, years_range,
                                           net_income)
    eps_fig = _make_eps_plot(scenarios, colors_map, years_range, eps)
    st.plotly_chart(revenue_fig, use_container_width=True)
    st.plotly_chart(net_income_fig, use_container_width=True)
    st.plotly_chart(eps_fig, use_container_width=True)

    st.subheader("Projected Stock Price")
    pe_ratios = [20, 40, 60, 80, 100, 120]

    def get_price_col_name(s):
        return f"{s.capitalize()} Price ($)"

    price_df = pd.DataFrame(columns=[get_price_col_name(s) for s in scenarios],
                            index=pe_ratios)
    price_df.index.name = "PE Ratio"
    for s in scenarios:
        for pe_ratio in pe_ratios:
            price_df.loc[pe_ratio, get_price_col_name(
                s)] = f"{round(eps[s][-1] * pe_ratio, 2):,.2f}"
    st.table(price_df)

    st.subheader("Export Results")

    if st.button("📄 Export to PDF"):
        pdf_bytes = generate_pdf_report(name, shares_outstanding, years,
                                        rev_streams, rev_per_stream,
                                        current_revenue, current_margin,
                                        growth_inputs, final_margins,
                                        scenarios, revenues, eps, price_df,
                                        net_income_fig, eps_fig)

        st.download_button(
            label="📥 Download PDF Report",
            data=pdf_bytes,
            file_name=
            f"{name}_stock_projection_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf")


def _add_trace(fig, scenario, colors_map, years_range, net_income):
    fig.add_trace(
        go.Scatter(x=years_range,
                   y=net_income[scenario],
                   mode='lines+markers',
                   name=f"Net Income - {scenario.capitalize()}",
                   line=dict(color=colors_map[scenario], width=3),
                   marker=dict(color=colors_map[scenario], size=8)))


def _make_revenue_plot(scenarios, colors_map, years_range, revenue):
    fig = go.Figure()
    for scenario in scenarios:
        _add_trace(fig, scenario, colors_map, years_range, revenue)
    _update_fig(fig, "Revenue Projections", "Year", "Value ($M)")
    return fig


def _make_net_income_plot(scenarios, colors_map, years_range, net_income):
    fig = go.Figure()
    for scenario in scenarios:
        _add_trace(fig, scenario, colors_map, years_range, net_income)
    _update_fig(fig, "Net Income Projections", "Year", "Value ($M)")
    return fig


def _make_eps_plot(scenarios, colors_map, years_range, eps):
    fig = go.Figure()
    for scenario in scenarios:
        _add_trace(fig, scenario, colors_map, years_range, eps)
    _update_fig(fig, "EPS Projections", "Year", "Value ($)")
    return fig


def _update_fig(fig, title, xaxis_title, yaxis_title):
    fig.update_layout(title=title,
                      xaxis_title=xaxis_title,
                      yaxis_title=yaxis_title,
                      hovermode="x unified",
                      xaxis=dict(showgrid=True,
                                 gridwidth=1,
                                 gridcolor='lightgray'),
                      yaxis=dict(showgrid=True,
                                 gridwidth=1,
                                 gridcolor='lightgray'))


def _set_table_style(table):
    table.setStyle(
        TableStyle([  #('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica')
        ]))

    for direct in [(-1, 0), (0, -1)]:
        table.setStyle(
            TableStyle([
                ('BACKGROUND', (0, 0), direct, colors.grey),
                ('TEXTCOLOR', (0, 0), direct, colors.whitesmoke),
                ('FONTNAME', (0, 0), direct, 'Helvetica-Bold'),
                #('BOTTOMPADDING', (0, 0), direct, 12)
            ]))


def _plotly_fig_to_pdf_img(fig):
    net_income_img_bytes = fig.to_image(format='png', width=800, height=500)
    net_income_img_buffer = io.BytesIO(net_income_img_bytes)
    net_income_img_buffer.seek(0)
    img = Image(net_income_img_buffer, width=6 * inch, height=3.75 * inch)
    return img


def generate_pdf_report(name, shares_outstanding, years, rev_streams,
                        rev_per_stream, current_revenue, current_margin,
                        growth_inputs, final_margins, scenarios, revenues, eps,
                        price_df, net_income_fig, eps_fig):
    """Generate a comprehensive PDF report of the stock projection analysis."""

    LARGE_SPACE = 18
    SMALL_SPACE = 9

    # Create PDF buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    story = []
    styles = getSampleStyleSheet()

    # Set default font to Helvetica (similar to Calibri)
    styles['Normal'].fontName = 'Helvetica'
    styles['Heading1'].fontName = 'Helvetica-Bold'
    styles['Heading2'].fontName = 'Helvetica-Bold'
    styles['Heading3'].fontName = 'Helvetica-Bold'

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    story.append(Paragraph(f"{name} Stock Projection Analysis", title_style))
    story.append(Spacer(1, LARGE_SPACE))

    # Input Parameters
    story.append(Paragraph("Input Parameters", styles['Heading2']))
    story.append(Spacer(1, SMALL_SPACE))

    # Company and financial parameters
    input_data = [
        ['Parameter', 'Value'],
        ['Company Name', name],
        ['Outstanding Shares', f"{shares_outstanding:,}"],
        ['Projection Period (Years)', str(years)],
        ['Current Total Revenue', f"${current_revenue:,.0f}M"],
        ['Current Operating Margin', f"{current_margin*100:.1f}%"],
        [
            'Current Operating Income',
            f"${current_revenue * current_margin:,.0f}M"
        ],
    ]

    input_table = Table(input_data, colWidths=[2 * inch, 3 * inch])
    _set_table_style(input_table)
    story.append(input_table)
    story.append(Spacer(1, LARGE_SPACE))

    # Revenue Streams
    story.append(Paragraph("Revenue Streams", styles['Heading3']))
    story.append(Spacer(1, SMALL_SPACE))

    rev_data = [['Revenue Stream', 'Current Revenue ($M)']]
    rev_data.append(["Total", f"{current_revenue:,.0f}"])
    for stream, revenue in rev_per_stream.items():
        rev_data.append([stream, f"{revenue:,.0f}"])

    rev_table = Table(rev_data, colWidths=[2 * inch, 3 * inch])
    _set_table_style(rev_table)
    story.append(rev_table)
    story.append(Spacer(1, LARGE_SPACE))

    # Growth Assumptions
    story.append(Paragraph("Growth Assumptions", styles['Heading3']))
    story.append(Spacer(1, SMALL_SPACE))

    growth_data = [['Revenue Stream', 'Bear (%)', 'Base (%)', 'Bull (%)']]
    for stream in rev_streams:
        growth_data.append([
            stream, f"{growth_inputs[stream]['bear']*100:.1f}",
            f"{growth_inputs[stream]['base']*100:.1f}",
            f"{growth_inputs[stream]['bull']*100:.1f}"
        ])

    growth_table = Table(growth_data,
                         colWidths=[2 * inch, 1 * inch, 1 * inch, 1 * inch])
    _set_table_style(growth_table)
    story.append(growth_table)
    story.append(Spacer(1, LARGE_SPACE))

    # Margin Assumptions
    story.append(Paragraph("Margin Assumptions", styles['Heading3']))
    story.append(Spacer(1, SMALL_SPACE))

    margin_data = [['', 'Bear', 'Base', 'Bull'],
                   [
                       'Final Operating Margin (%)',
                       f"{final_margins['bear']*100:.1f}",
                       f"{final_margins['base']*100:.1f}",
                       f"{final_margins['bull']*100:.1f}"
                   ]]
    margin_table = Table(margin_data,
                         colWidths=[2 * inch, 1 * inch, 1 * inch, 1 * inch])
    _set_table_style(margin_table)
    story.append(margin_table)
    story.append(PageBreak())

    # Financial Projections Charts
    story.append(Paragraph("Financial Projections", styles['Heading2']))
    story.append(Spacer(1, SMALL_SPACE))

    # Convert Plotly figures to static images
    try:
        # Net Income Chart
        story.append(Paragraph("Net Income Projections", styles['Heading3']))
        story.append(Spacer(1, SMALL_SPACE))
        net_income_img = _plotly_fig_to_pdf_img(net_income_fig)
        story.append(net_income_img)
        story.append(Spacer(1, LARGE_SPACE))

        # EPS Chart
        story.append(
            Paragraph("Earnings Per Share (EPS) Projections",
                      styles['Heading3']))
        story.append(Spacer(1, SMALL_SPACE))
        eps_img = _plotly_fig_to_pdf_img(eps_fig)
        story.append(eps_img)

    except Exception as e:
        # Fallback if chart generation fails
        story.append(
            Paragraph(
                f"Note: Charts could not be generated for PDF export. Error: {str(e)}",
                ParagraphStyle('Error',
                               parent=styles['Normal'],
                               textColor=colors.red)))
    story.append(PageBreak())

    # Projected Revenue, Income, EPS
    story.append(Paragraph("Projected Growth", styles['Heading2']))
    story.append(Spacer(1, SMALL_SPACE))
    growth_data = [['Metric'] + [f"{s.capitalize()}" for s in scenarios]]
    growth_data.append(['Revenue ($M)'] +
                       [f"{revenues[s][-1]:,.2f}" for s in scenarios])
    growth_data.append(
        ['Net Income ($M)'] +
        [f"{revenues[s][-1] * final_margins[s]:,.2f}" for s in scenarios])
    growth_data.append(['EPS ($)'] + [f"{eps[s][-1]:,.2f}" for s in scenarios])
    growth_table = Table(
        growth_data,
        colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    _set_table_style(growth_table)
    story.append(growth_table)
    story.append(Spacer(1, LARGE_SPACE))

    # Projected Stock Prices
    story.append(Paragraph("Projected Stock Prices", styles['Heading2']))
    story.append(Spacer(1, SMALL_SPACE))

    # Convert price_df to list for PDF table
    price_data = [['PE Ratio'] +
                  [f"{s.capitalize()} Price ($)" for s in scenarios]]
    for pe_ratio in price_df.index:
        row = [str(pe_ratio)]
        for scenario in scenarios:
            price = eps[scenario][-1] * pe_ratio
            row.append(f"{price:,.2f}")
        price_data.append(row)

    price_table = Table(
        price_data, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    _set_table_style(price_table)
    story.append(price_table)
    story.append(Spacer(1, LARGE_SPACE))

    # Footer
    story.append(
        Paragraph(
            f"Report generated on {datetime.datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            ParagraphStyle('Footer',
                           parent=styles['Normal'],
                           fontName='Helvetica',
                           fontSize=8,
                           alignment=1)))

    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


if __name__ == "__main__":
    main()
