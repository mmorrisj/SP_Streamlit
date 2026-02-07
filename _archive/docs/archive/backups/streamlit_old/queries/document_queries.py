import pandas as pd
import streamlit as st
import ast

# Modern SQLAlchemy 2.0 imports
from backend.models import Document, Category, Subcategory, InitiatingCountry, RecipientCountry
from backend.database import get_session, get_engine
from sqlalchemy import func, desc, select, text
from sqlalchemy.sql import exists, Join
from backend.scripts.utils import Config

cfg = Config.from_yaml()

def compile_query(query):
    """Compile SQLAlchemy query to string for debugging."""
    engine = get_engine()
    if hasattr(query, "statement"):
        query = query.statement
    return str(query.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))

def apply_join(
    stmt,
    table=None,
    include_documents: bool = True,
    initiating: bool     = False,
    recipient: bool      = False,
    category: bool       = False,
    subcategory: bool    = False,
):
    # 1) Build a set of already-joined table names
    joined = set()
    for frm in stmt.get_final_froms():
        # plain table, has .name
        if hasattr(frm, 'name'):
            joined.add(frm.name)
        # a Join object, pull left/right table names
        elif isinstance(frm, Join):
            left, right = frm.left, frm.right
            if hasattr(left, 'name'):
                joined.add(left.name)
            if hasattr(right, 'name'):
                joined.add(right.name)

    # 2) Ensure Document is first, if requested
    if include_documents and table is not Document and 'documents' not in joined:
        stmt = stmt.join(Document, Document.doc_id == table.doc_id)
        joined.add('documents')

    # 3) Now hook up each other table off of Document
    if category and 'categories' not in joined:
        stmt = stmt.join(Category, Category.doc_id == Document.doc_id)
        joined.add('categories')

    if initiating and 'initiating_countries' not in joined:
        stmt = stmt.join(
            InitiatingCountry,
            InitiatingCountry.doc_id == Document.doc_id
        )
        joined.add('initiating_countries')

    if recipient and 'recipient_countries' not in joined:
        stmt = stmt.join(
            RecipientCountry,
            RecipientCountry.doc_id == Document.doc_id
        )
        joined.add('recipient_countries')

    if subcategory and 'subcategories' not in joined:
        stmt = stmt.join(Subcategory, Subcategory.doc_id == Document.doc_id)
        joined.add('subcategories')

    return stmt

def standard_filter(stmt, table=None, initiating=False, recipient=False, category=False, subcategory=False, date_range=False):
    if initiating:
        stmt = stmt.where(InitiatingCountry.initiating_country.in_(cfg.influencers))
    if recipient:
        stmt = stmt.where(RecipientCountry.recipient_country.in_(cfg.recipients))
    if category:
        stmt = stmt.where(Category.category.in_(cfg.categories))
    if subcategory:
        stmt = stmt.where(Subcategory.subcategory.in_(cfg.subcategories))
    if date_range:
        stmt = stmt.where(Document.date >= cfg.start_date)
    return stmt

# Build a CTE of just the doc_ids you ever care about:
filtered_docs = (
    select(Document.doc_id)
    .distinct()
    .select_from(Document)
    .join(InitiatingCountry,   InitiatingCountry.doc_id   == Document.doc_id)
    .join(RecipientCountry,    RecipientCountry.doc_id    == Document.doc_id)
    .where(
        InitiatingCountry.initiating_country.in_(cfg.influencers),
        RecipientCountry.recipient_country   .in_(cfg.recipients),
        Document.date >= cfg.start_date,  # if you have a default end_date
    )
    ).cte("filtered_docs")

def apply_filters(stmt, table=None, country_list='ALL', category='ALL', subcategory='ALL', start_date=None, end_date=None):
    if country_list != "ALL":
        stmt = stmt.where(InitiatingCountry.initiating_country.in_(country_list))

    if category != "ALL":
        stmt = stmt.where(Category.category == category)

    if subcategory != "ALL":
        stmt = stmt.where(Subcategory.subcategory == subcategory)

    if start_date:
        stmt = stmt.where(Document.date >= start_date)
    else:
        stmt = stmt.where(Document.date >= cfg.start_date)

    if end_date:
        stmt = stmt.where(Document.date <= end_date)

    return stmt

def set_start_date(start_date=None):
    return start_date if start_date else cfg.start_date

def set_start_date(start_date=None):
    if start_date:
        return start_date
    else:
        return cfg.start_date
@st.cache_data
def initiating_country_list():
    stmt = (select(InitiatingCountry.initiating_country)
        .where(InitiatingCountry.initiating_country.in_(cfg.influencers)))
    with engine.connect() as conn: 
       df = pd.read_sql(stmt, conn)
       return sorted(list(set([x for x in df['initiating_country']])))

@st.cache_data
def recipient_country_list():
    stmt = (select(RecipientCountry.recipient_country)
        .where(RecipientCountry.recipient_country.in_(cfg.recipients)))
    with engine.connect() as conn: 
       df = pd.read_sql(stmt, conn)
       return sorted(list(set([x for x in df['recipient_country']])))

@st.cache_data
def category_list():
    stmt = (select(Category.category)
        .where(Category.category.in_(cfg.categories)))
    with engine.connect() as conn: 
       df = pd.read_sql(stmt, conn)
       return sorted(list(set([x for x in df['category']])))
       
@st.cache_data
def subcategory_list():
    stmt = (select(Subcategory.subcategory)
        .where(Subcategory.subcategory.in_(cfg.subcategories)))
    with engine.connect() as conn: 
       df = pd.read_sql(stmt, conn)
       return sorted(list(set([x for x in df['subcategory']])))

@st.cache_data
def get_document_counts_per_week(
    country_list='ALL',
    category='ALL',
    subcategory='ALL',
    start_date=None,
    end_date=None
):
    # 1) normalize your incoming date
    start_date = set_start_date(start_date)

    # 2) build the core Select
    stmt = (
        select(
            func.date_trunc('week', Document.date).label('week_start'),
            func.count(func.distinct(Document.doc_id)).label('doc_count')
        )
        .select_from(Document)
        .join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
        .join(RecipientCountry,  Document.doc_id == RecipientCountry.doc_id)
        .join(Category,           Document.doc_id == Category.doc_id)
        .where(
            # use the function argument, not cfg.start_date
            Document.date >= start_date,
            # later you can add filters on country_list, category, subcategory
            InitiatingCountry.initiating_country.in_(cfg.influencers),
            RecipientCountry.recipient_country.in_(cfg.recipients),
        )
        .group_by('week_start')
        .order_by('week_start')
    )

    # 3) pass the Select object *directly* to pandas.read_sql
    with engine.begin() as conn:
        df = pd.read_sql(stmt, conn)

    return df

@st.cache_data
def get_subcategory_distribution_by_document_count(country_list='ALL',category='ALL',subcategory='ALL',start_date=None,end_date=None):
    # Build the base select
    start_date = set_start_date(start_date)
    stmt = (
        select(
            Subcategory.subcategory,
            func.count(func.distinct(Subcategory.doc_id)).label('doc_count')
        )).select_from(Subcategory).join(filtered_docs, filtered_docs.c.doc_id == Subcategory.doc_id)
    stmt = apply_join(stmt,Subcategory,initiating=True,recipient=True,category=True)
    stmt = apply_filters(stmt,table=Subcategory,country_list=country_list,
                        category=category,
                        subcategory=subcategory,
                        start_date=start_date,
                        end_date=end_date)
    
        # Group by and order by
    stmt = stmt.group_by(Subcategory.subcategory).order_by(desc('doc_count'))
    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_top_influencers_by_document_count(country_list='ALL', category='ALL', subcategory='ALL', start_date=None, end_date=None):
    start_date = set_start_date(start_date)
    
    stmt = (
        select(
            InitiatingCountry.initiating_country,
            func.count(func.distinct(InitiatingCountry.doc_id)).label('doc_count')
        ).select_from(InitiatingCountry)
        .join(Document,InitiatingCountry.doc_id==Document.doc_id)
        .join(RecipientCountry,Document.doc_id==RecipientCountry.doc_id)
        .join(Category,Document.doc_id==Category.doc_id)
        .where(InitiatingCountry.initiating_country.in_(cfg.influencers),
        RecipientCountry.recipient_country.in_(cfg.recipients),
        Document.date >=cfg.start_date)
        )
    # stmt = apply_filters(stmt,table=InitiatingCountry, country_list=country_list,
    #                      category=category,
    #                      subcategory=subcategory,
    #                      start_date=start_date,
    #                      end_date=end_date)

    stmt = stmt.group_by(InitiatingCountry.initiating_country)

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_top_recipients_by_document_count(country_list='ALL',category='ALL',subcategory='ALL',start_date=None,end_date=None):
    start_date = set_start_date(start_date)
    stmt = (
        select(RecipientCountry.recipient_country,
        func.count(func.distinct(RecipientCountry.doc_id)).label('doc_count')
        )).select_from(RecipientCountry).join(filtered_docs, filtered_docs.c.doc_id == RecipientCountry.doc_id)
    stmt = apply_join(stmt,RecipientCountry,initiating=True,category=True,subcategory=True)
    stmt = apply_filters(stmt,table=RecipientCountry,country_list=country_list,
                        category=category,
                        subcategory=subcategory,
                        start_date=start_date,
                        end_date=end_date)

    stmt = stmt.group_by(RecipientCountry.recipient_country)
    stmt = stmt.order_by(desc('doc_count'))
    stmt = stmt.limit(10)

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_category_distribution_by_document_count(country_list='ALL',category='ALL',subcategory='ALL',start_date=None,end_date=None):
    start_date = set_start_date(start_date)
    stmt = (select(Category.category,
        func.count(func.distinct(Category.doc_id)).label('doc_count')
        ).select_from(Category)
        .join(Document,Category.doc_id==Document.doc_id)
        .join(RecipientCountry,Document.doc_id==RecipientCountry.doc_id)
        .join(InitiatingCountry,Document.doc_id==InitiatingCountry.doc_id)
        .where(InitiatingCountry.initiating_country.in_(cfg.influencers),
        RecipientCountry.recipient_country.in_(cfg.recipients),
        Category.category.in_(cfg.categories),
        Document.date >=cfg.start_date)
        )
    stmt = stmt.group_by(Category.category)
    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_category_distribution_by_document_count_by_country(country_list='ALL',category='ALL',subcategory='ALL',start_date=None,end_date=None):
    start_date = set_start_date(start_date)
    stmt = (select(
            InitiatingCountry.initiating_country,
            Category.category,
            func.count(func.distinct(Category.doc_id)).label('doc_count')
        ).select_from(Category)
        .join(Document,Category.doc_id==Document.doc_id)
        .join(RecipientCountry,Document.doc_id==RecipientCountry.doc_id)
        .join(InitiatingCountry,Document.doc_id==InitiatingCountry.doc_id)
        .where(InitiatingCountry.initiating_country.in_(cfg.influencers),
        RecipientCountry.recipient_country.in_(cfg.recipients),
        Category.category.in_(cfg.categories),
        Document.date >=cfg.start_date)
        )
    stmt = stmt.group_by(
        InitiatingCountry.initiating_country,
        Category.category
        ).order_by(
            InitiatingCountry.initiating_country,
            desc('doc_count')
        )

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_category_count_over_time(country_list='ALL',category='ALL',subcategory='ALL',start_date=None,end_date=None):
    start_date = set_start_date(start_date)
    stmt = (select(
    func.date_trunc('month', Document.date).label('month'),
    func.count(func.distinct(Category.doc_id)).label('category_count')
    ).select_from(Category)
    .join(Document,Category.doc_id==Document.doc_id)
    .join(RecipientCountry,Document.doc_id==RecipientCountry.doc_id)
    .join(InitiatingCountry,Document.doc_id==InitiatingCountry.doc_id)
    .where(InitiatingCountry.initiating_country.in_(cfg.influencers),
    RecipientCountry.recipient_country.in_(cfg.recipients),
    Category.category.in_(cfg.categories),
    Document.date >=cfg.start_date)
    )
    stmt = stmt.group_by(
            'month'
            ).order_by(
                desc('category_count')
            )

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

@st.cache_data
def get_category_count_over_time(country='ALL',start_date=None):
    from backend.scripts.models import SoftPowerActivity
    start_date = set_start_date(start_date)
    
    stmt = (select(func.date_trunc('month', SoftPowerActivity.date).label('month_start'),
            func.count(SoftPowerActivity.id)).select_from(SoftPowerActivity)).where(Category.category.in_(cfg.categories),
            Document.date >=cfg.start_date)
    
    stmt = stmt.group_by(
            'month'
            ).order_by(
                desc('category_count')
            )

    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        return df

#get Category df
@st.cache_data
def get_category_df():
    stmt = select(Category).order_by(Category.category)
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df

#get Subcategory df
@st.cache_data
def get_subcategory_df():
    stmt = select(Subcategory).order_by(Subcategory.subcategory)
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df
#get activity df
@st.cache_data
def get_activity_df(country_list=None,start_date=None,end_date=None):
    if start_date is None:
        start_date = '2024-08-01'
    if end_date is None:
        end_date = pd.to_datetime('today').strftime('%Y-%m-%d')
    stmt = select(SoftPowerActivity).order_by(SoftPowerActivity.date.desc())
    stmt = stmt.filter(SoftPowerActivity.date.between(start_date, end_date),
                       SoftPowerActivity.initiating_country.in_(cfg.influencers),
                       SoftPowerActivity.recipient_country.in_(cfg.recipients))
    if country_list and country_list != "ALL":
        stmt = stmt.filter(SoftPowerActivity.initiating_country.in_(country_list))
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df

# get daily df
@st.cache_data
def get_daily_df():
    stmt = select(DailySummary).order_by(DailySummary.date.desc())
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df

@st.cache_data
def get_document_dates(country_list=None,start_date=None,end_date=None):
    if start_date is None:
        start_date = '2024-08-01'
    stmt = select(Document.doc_id,Document.date).order_by(Document.date.desc())
    stmt = stmt.join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
    stmt = stmt.join(RecipientCountry, Document.doc_id == RecipientCountry.doc_id)
    stmt = stmt.filter(InitiatingCountry.initiating_country.in_(cfg.influencers),
                       RecipientCountry.recipient_country.in_(cfg.recipients),
                       Document.date >= start_date)
    if country_list and country_list != "ALL":
        stmt = stmt.filter(InitiatingCountry.initiating_country.in_(country_list))
    if end_date:
        stmt = stmt.filter(Document.date <= end_date)
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
    return df

@st.cache_data
def get_last_week_of_documents(country_list=None,end_date=None):
    #convert mmmm-mm-dd to datetime
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date)
    if end_date is None:
        end_date = pd.to_datetime('today')
    start_date = end_date - pd.Timedelta(weeks=1)
    stmt = select(Document).where(Document.date.between(start_date, end_date)).order_by(Document.date.desc())   
    stmt = stmt.join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
    stmt = stmt.join(RecipientCountry, Document.doc_id == RecipientCountry.doc_id)
    stmt = stmt.filter(InitiatingCountry.initiating_country.in_(cfg.influencers),
                       RecipientCountry.recipient_country.in_(cfg.recipients))
    if country_list and country_list != "ALL":
        stmt = stmt.filter(InitiatingCountry.initiating_country.in_(country_list))
    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
    return df

@st.cache_data
def get_most_recent_daily_summary(country_list=None,date=None):
    stmt = select(DailySummary).order_by(DailySummary.date.desc()).limit(1)
    if country_list and country_list != "ALL":
        stmt = stmt.filter(DailySummary.initiating_country.in_(country_list))
    if date:
        stmt = stmt.filter(DailySummary.date == date)
    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
    return df
    
@st.cache_data
def get_date_documents(date,country=None,category=None):
    stmt = select(Document).where(Document.date == date).order_by(Document.date.desc())
    if country and country != "ALL":
        stmt = stmt.join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
        stmt = stmt.filter(InitiatingCountry.initiating_country == country)
    else:
        stmt = stmt.join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
        stmt = stmt.filter(InitiatingCountry.initiating_country.in_(cfg.influencers))
        stmt = stmt.join(RecipientCountry, Document.doc_id == RecipientCountry.doc_id)
        stmt = stmt.filter(RecipientCountry.recipient_country.in_(cfg.recipients))
    if category and category != "ALL":
        stmt = stmt.join(Category, Document.doc_id == Category.doc_id)
        stmt = stmt.filter(Category.category == category)
    with engine.connect() as conn:
        df = pd.read_sql(stmt, conn)
        df.drop_duplicates(subset=['doc_id'], inplace=True)
    return df

@st.cache_data
def fetch_daily_counts(country_list=None):
    raw = (
        get_document_dates(country_list=country_list)
        .drop_duplicates(subset=["doc_id","date"])
    )
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    daily = (
        raw
        .groupby("date", as_index=False)
        .agg(count=("doc_id","nunique"))
        .sort_values("date")
    )
    return daily,raw

def source_counts(date_docs,top_n=10):
    date_docs['source_name'] = date_docs['source_name'].fillna('Unknown')
    source_counts = date_docs['source_name'].value_counts().reset_index()
    source_counts.columns = ['Source','References']
    return source_counts[:top_n].to_html()

def get_category(category=None,country=None):
    stmt = select(Category,Document.date).order_by(Category.category)
    stmt = stmt.join(Document, Category.doc_id == Document.doc_id)
    stmt = stmt.join(InitiatingCountry, Category.doc_id == InitiatingCountry.doc_id)
    stmt = stmt.join(RecipientCountry, Category.doc_id == RecipientCountry.doc_id)
    stmt = stmt.filter(InitiatingCountry.initiating_country.in_(cfg.influencers),
                       RecipientCountry.recipient_country.in_(cfg.recipients))
    if category and category != "ALL":
        stmt = stmt.filter(Category.category == category)
    if country and country != "ALL":
        stmt = stmt.filter(InitiatingCountry.initiating_country == country)

    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
        df.drop_duplicates(subset=['doc_id'], inplace=True)
        df.reset_index(inplace=True,drop=True)
        df['date'] = pd.to_datetime(df['date'])
    
    return df

@st.cache_data
def get_daily_category_article_counts(category=None, country=None):
    df = get_category(category=category, country=country)
    if df.empty:
        return pd.DataFrame(columns=['date', 'doc_count'])
    #filter out rows with null dates
    df = df[df['date'].notnull()]
    #filter by start date
    df = df[df['date'] >= pd.to_datetime('2024-08-01')]

    # Group by date and count documents
    daily_counts = df.groupby(df['date'].dt.date).size().reset_index(name='doc_count')
    daily_counts['date'] = pd.to_datetime(daily_counts['date'])
    
    return daily_counts

def visualize_category_z_score(df):
    if df.empty:
        return alt.Chart().mark_text(text='No data available').properties(width=800, height=400)

    # Calculate z-scores
    df['z_score'] = (df['doc_count'] - df['doc_count'].mean()) / df['doc_count'].std()

    chart = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X('date:T', title='Date'),
        y=alt.Y('z_score:Q', title='Z-Score of Document Count'),
        tooltip=['date:T', 'doc_count:Q', 'z_score:Q']
    ).properties(
        title=f'Z-Score of Document Count for {category} in {country}',
        width=800,
        height=400
    ).interactive()

    return chart.configure_title(
        fontSize=20,
        anchor='start',
        color='black'
    ).configure_axis(
        labelFontSize=12,
        titleFontSize=14
    ).configure_legend(
        labelFontSize=12,
        titleFontSize=14
    )

def get_most_recent_daily_date(country):
    stmt = select(DailySummary.date).where(DailySummary.initiating_country==country)
    with engine.connect() as conn: 
        df = pd.read_sql(stmt, conn)
        return max(df['date'])