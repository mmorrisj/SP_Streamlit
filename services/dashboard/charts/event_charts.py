"""
Chart visualization functions for master events and canonical events.
"""
import altair as alt
import pandas as pd


def top_master_events_chart(df):
    """
    Create horizontal bar chart showing top master events by article count.

    Args:
        df: DataFrame with columns: canonical_name, total_articles, child_count, days_span

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    # Add hover tooltip with additional info
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('total_articles:Q', title='Total Articles'),
        y=alt.Y('canonical_name:N', title='Master Event', sort='-x'),
        color=alt.Color('initiating_country:N', title='Country'),
        tooltip=[
            alt.Tooltip('canonical_name:N', title='Event'),
            alt.Tooltip('initiating_country:N', title='Country'),
            alt.Tooltip('total_articles:Q', title='Articles'),
            alt.Tooltip('child_count:Q', title='Child Events'),
            alt.Tooltip('days_span:Q', title='Days Active')
        ]
    ).properties(
        title='Top Master Events by Article Count',
        width=700,
        height=500
    ).interactive()

    return chart


def events_by_country_chart(df):
    """
    Create stacked bar chart showing master event counts and articles by country.

    Args:
        df: DataFrame with columns: initiating_country, master_event_count, total_articles

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    # Create chart showing both event counts and article volumes
    base = alt.Chart(df).encode(
        x=alt.X('initiating_country:N', title='Country', sort='-y')
    )

    events_chart = base.mark_bar(color='steelblue').encode(
        y=alt.Y('master_event_count:Q', title='Master Events'),
        tooltip=[
            alt.Tooltip('initiating_country:N', title='Country'),
            alt.Tooltip('master_event_count:Q', title='Master Events'),
            alt.Tooltip('child_event_count:Q', title='Child Events'),
            alt.Tooltip('total_articles:Q', title='Total Articles')
        ]
    ).properties(
        title='Master Events by Country',
        width=600,
        height=400
    )

    return events_chart


def temporal_trends_chart(df):
    """
    Create line chart showing article trends over time.

    Args:
        df: DataFrame with columns: date, article_count, event_count

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    # Article volume line chart
    article_line = alt.Chart(df).mark_line(
        point=True,
        color='steelblue'
    ).encode(
        x=alt.X('date:T', title='Date'),
        y=alt.Y('article_count:Q', title='Article Count'),
        tooltip=[
            alt.Tooltip('date:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('article_count:Q', title='Articles'),
            alt.Tooltip('event_count:Q', title='Events')
        ]
    )

    # Event count line chart
    event_line = alt.Chart(df).mark_line(
        point=True,
        color='orange',
        strokeDash=[5, 5]
    ).encode(
        x=alt.X('date:T'),
        y=alt.Y('event_count:Q', title='Event Count'),
        tooltip=[
            alt.Tooltip('date:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('event_count:Q', title='Events')
        ]
    )

    # Combine charts
    chart = alt.layer(article_line, event_line).resolve_scale(
        y='independent'
    ).properties(
        title='Daily Article and Event Trends',
        width=800,
        height=400
    ).interactive()

    return chart


def category_breakdown_chart(df):
    """
    Create pie/donut chart showing category distribution.

    Args:
        df: DataFrame with columns: category, master_event_count, total_articles

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
        theta=alt.Theta('total_articles:Q', title='Total Articles'),
        color=alt.Color('category:N', title='Category'),
        tooltip=[
            alt.Tooltip('category:N', title='Category'),
            alt.Tooltip('master_event_count:Q', title='Master Events'),
            alt.Tooltip('total_articles:Q', title='Articles')
        ]
    ).properties(
        title='Master Events by Category',
        width=500,
        height=400
    )

    return chart


def recipient_impact_chart(df):
    """
    Create heatmap showing recipient country impact by initiating country.

    Args:
        df: DataFrame with columns: recipient, initiating_country, master_event_count, total_articles

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    # Create heatmap
    chart = alt.Chart(df).mark_rect().encode(
        x=alt.X('initiating_country:N', title='Initiating Country'),
        y=alt.Y('recipient:N', title='Recipient Country'),
        color=alt.Color('total_articles:Q', title='Total Articles', scale=alt.Scale(scheme='blues')),
        tooltip=[
            alt.Tooltip('initiating_country:N', title='Initiating'),
            alt.Tooltip('recipient:N', title='Recipient'),
            alt.Tooltip('master_event_count:Q', title='Master Events'),
            alt.Tooltip('total_articles:Q', title='Articles')
        ]
    ).properties(
        title='Recipient Country Impact by Initiating Country',
        width=600,
        height=400
    )

    return chart


def master_event_timeline_chart(df):
    """
    Create stacked area chart showing master event timeline with child events.

    Args:
        df: DataFrame with columns: date, event_name, article_count, doc_count

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    chart = alt.Chart(df).mark_area(opacity=0.7).encode(
        x=alt.X('date:T', title='Date'),
        y=alt.Y('article_count:Q', title='Article Count', stack='zero'),
        color=alt.Color('event_name:N', title='Event Name'),
        tooltip=[
            alt.Tooltip('date:T', title='Date', format='%Y-%m-%d'),
            alt.Tooltip('event_name:N', title='Event'),
            alt.Tooltip('article_count:Q', title='Articles'),
            alt.Tooltip('doc_count:Q', title='Documents')
        ]
    ).properties(
        title='Master Event Timeline (Stacked by Child Events)',
        width=800,
        height=400
    ).interactive()

    return chart


def country_article_comparison_chart(df):
    """
    Create grouped bar chart comparing article volumes across countries.

    Args:
        df: DataFrame with columns: initiating_country, total_articles

    Returns:
        Altair chart
    """
    if df.empty:
        return alt.Chart().mark_text(
            text='No data available',
            size=20
        ).properties(width=800, height=400)

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('initiating_country:N', title='Country', sort='-y'),
        y=alt.Y('total_articles:Q', title='Total Articles'),
        color=alt.Color('initiating_country:N', legend=None),
        tooltip=[
            alt.Tooltip('initiating_country:N', title='Country'),
            alt.Tooltip('master_event_count:Q', title='Master Events'),
            alt.Tooltip('total_articles:Q', title='Total Articles')
        ]
    ).properties(
        title='Article Volume by Country',
        width=600,
        height=400
    )

    return chart
