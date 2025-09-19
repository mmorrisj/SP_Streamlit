from backend.scripts.dsr import process_dsr
from backend.scripts.flatten import normalize_data, flatten_event
from backend.scripts.sp_tokenize import run_tokenize
from backend.scripts.daily import daily_summaries
from backend.scripts.utils import Config
from backend.app import app
from backend.extensions import db
from backend.scripts.models import Document,CountrySummary,InitiatingCountry,RecipientCountry,Event,EventSources,SoftPowerActivity,SoftPowerActivityCategory,SoftPowerActivitySource,SoftPowerActivitySubcategory
cfg = Config.from_yaml()


source_sys_prompt = '''You are an expert writer and editor for an international relations firm. Your task is to identify the **most relevant sources** that directly support the specific claims and statements of fact made in the SUMMARY.

Based on the TITLE, SUMMARY, and REPORTING provided, carefully review the SUMMARY. From the REPORTING, select ONLY those sources (doc_ids) that **explicitly and substantively validate or provide direct evidence** for the claims or statements of fact made in the SUMMARY.

**DO NOT include sources that are only tangentially related, generally relevant, or do not provide direct factual support for the SUMMARY’s content.**

Return ONLY a list of the doc_ids that best and most directly support the SUMMARY, in this format:

[<LIST OF DOC_IDS>]

IMPORTANT: If NO sources in the REPORTING substantively validate the SUMMARY, return an empty list ([]).

**ONLY OUTPUT THE LIST—NO OTHER TEXT OR EXPLANATION.**
'''
source_user_prompt = ''' 
TITLE: {title},

SUMMARY: {summary},

REPORTING: {reports}
'''

def summary_reporting(country,start_date,end_date,category,recipient=None):
    filename = file_name(country=country,start_date=start,end_date=end,category=category,recipient=recipient)
    app.app_context().push()
    db.session.remove()
    db.engine.dispose()
    reporting = (db.session.query(Document.doc_id,
                            Document.date,
                            Document.title,
                            Document.distilled_text,
                            Document.salience_justification,
                            Category.category,
                            TokenizedDocuments.tokens)
                            .join(Category,Document.doc_id==Category.doc_id)
                            .join(InitiatingCountry,Document.doc_id==InitiatingCountry.doc_id)
                            .join(RecipientCountry,Document.doc_id==RecipientCountry.doc_id)
                            .join(TokenizedDocuments,Document.doc_id==TokenizedDocuments.doc_id)
                            .filter(Document.date.between(start,end),
                            InitiatingCountry.initiating_country==country,
                            RecipientCountry.recipient_country.in_(cfg.recipients),
                            Category.category==category).all())
    df_reporting = pd.DataFrame([x for x in reporting])
    # If you know the date column names, e.g., "date"
    df_reporting["date"] = df_reporting["date"].astype(str)
    df_reporting.drop_duplicates(inplace=True)
    df_reporting.reset_index(inplace=True,drop=True)
    df_reporting.to_excel(f'./gai_summary/data/{filename}.xlsx')
    with open(os.path.join(cfg.gai_json,f'{filename}_report_text.json'),'w') as f:
        json.dump(df_reporting.to_dict(orient='records'),f,indent=4)

    str_reporting = ''
    str_reporting += f'TOTAL {country}-{category} REPORTS: {len(reporting)}\n'
    if reporting:
        if len(df_reporting) > 350:
            sample_ = random.sample(reporting, k=325)
            for r in sample_:
                str_reporting += f'{r}\n'
        else:
            for r in reporting:
                str_reporting += f'{r}\n'
    return reporting,str_reporting    

def summary_activities(country,start_date,end_date,category,recipient=None):
    filename = file_name(country=country,start_date=start,end_date=end,category=category,recipient=recipient)
    app.app_context().push()
    db.session.remove()
    db.engine.dispose()
    activities = db.session.query(SoftPowerActivity).filter(SoftPowerActivity.date.between(start,end),
                                                    SoftPowerActivity.initiating_country==country,
                                                    SoftPowerActivity.recipient_country.in_(cfg.recipients),
                                                    SoftPowerActivity.category.like(f"{category}")
                                                    ).all()
    df_ = pd.DataFrame([x.to_dict() for x in activities])
    # If you know the date column names, e.g., "date"
    df_["date"] = df_["date"].astype(str)
    with open(os.path.join(cfg.gai_json,f'{filename}_activities.json'),'w') as f:
        json.dump(df_.to_dict(orient='records'),f,indent=4)
    str_activities = ''
    str_activities += f'ACTIVITY REFERENCES: {len(activities)}\n'
    if activities:
        for a in activities:
            str_activities += f'{a.to_dict()}\n'
    return activities,str_activities

def summary_dailies(country,start_date,end_date,category,recipient=None):
    filename = file_name(country=country,start_date=start,end_date=end,category=category,recipient=recipient)
    app.app_context().push()
    db.session.remove()
    db.engine.dispose()
    dailies = (db.session.query(DailySummary)
                            .join(DailyCategory,DailySummary.id==DailyCategory.daily_id)
                            .filter(DailySummary.date.between(start,end),
                                                        DailySummary.initiating_country==country,
                                                        DailyCategory.category==category,
                                                        DailyRecipient.recipient_country.in_(cfg.recipients)
                                                        ).all()
    )
    df_ = pd.DataFrame([x.to_dict() for x in dailies])
    # If you know the date column names, e.g., "date"
    df_["date"] = df_["date"].astype(str)
    with open(os.path.join(cfg.gai_json,f'{filename}_dailies.json'),'w') as f:
        json.dump(df_.to_dict(orient='records'),f,indent=4)
    str_daily = ''
    if dailies:
        for d in dailies:
            str_daily += f'{d.to_dict()}\n'
    return dailies,str_daily
    
def summary_metrics(country,start_date,end_date,category,recipient=None,dataframe=False):
    app.app_context().push()
    db.session.remove()
    db.engine.dispose()
    metrics = (db.session.query(InitiatingCountry.initiating_country,func.count(InitiatingCountry.doc_id)
                .label("num_docs"))
                .group_by(InitiatingCountry.initiating_country)
                .order_by(func.count(InitiatingCountry.doc_id)
                .desc())
                .join(Document,InitiatingCountry.doc_id == Document.doc_id)
                .join(RecipientCountry,InitiatingCountry.doc_id == RecipientCountry.doc_id)
                .join(Category,Category.doc_id==RecipientCountry.doc_id)
                .filter(InitiatingCountry.initiating_country.in_(cfg.influencers),
                        Document.date.between(start,end),
                        Category.category==category,
                        RecipientCountry.recipient_country.in_(cfg.recipients)).all())
    df = pd.DataFrame(metrics, columns=["initiating_country", "num_docs"])
    df["initiating_country"] = df["initiating_country"].fillna("N/A")
    if dataframe:
        df.to_excel(os.path.join(cfg.gai_data,f'{filename}_metrics.xlsx'),index=False)

    str_metrics = df.to_markdown(index=False)  

    metrics = (db.session.query(RecipientCountry.recipient_country,func.count(RecipientCountry.doc_id)
            .label("num_docs"))
            .group_by(RecipientCountry.recipient_country)
            .order_by(func.count(RecipientCountry.doc_id)
            .desc())
            .join(Document,RecipientCountry.doc_id == Document.doc_id)
            .join(InitiatingCountry,RecipientCountry.doc_id==InitiatingCountry.doc_id)
            .join(Category,Category.doc_id==RecipientCountry.doc_id)
            .filter(RecipientCountry.recipient_country.in_(cfg.recipients),
                    InitiatingCountry.initiating_country==country,
                    Category.category==category,
                    Document.date.between(start,end)).all())
    df = pd.DataFrame(metrics, columns=["recipient_country", "num_docs"])
    df["recipient_country"] = df["recipient_country"].fillna("N/A")
    if dataframe:
        df.to_excel(os.path.join(cfg.gai_data,f'{filename}_rec_metrics.xlsx'),index=False)

    str_recipient_metrics = df.to_markdown(index=False)

    metrics = (db.session.query(Category.category,func.count(Category.doc_id)
            .label("num_docs"))
            .group_by(Category.category)
            .order_by(func.count(Category.doc_id)
            .desc())
            .join(Document,Category.doc_id == Document.doc_id)
            .join(InitiatingCountry,Category.doc_id==InitiatingCountry.doc_id)
            .join(RecipientCountry,Category.doc_id==RecipientCountry.doc_id)
            .filter(RecipientCountry.recipient_country.in_(cfg.recipients),
                    InitiatingCountry.initiating_country==country,
                    Document.date.between(start,end)).all())
    df = pd.DataFrame(metrics, columns=["category", "num_docs"])
    df["category"] = df["category"].fillna("N/A")
    if dataframe:
        df.to_excel(os.path.join(cfg.gai_data,f'{filename}_cat_metrics.xlsx'),index=False)
    str_category_metrics = df.to_markdown(index=False)

    metrics = (db.session.query(Subcategory.subcategory,func.count(Subcategory.doc_id)
            .label("num_docs"))
            .group_by(Subcategory.subcategory)
            .order_by(func.count(Subcategory.doc_id)
            .desc())
            .join(Document,Subcategory.doc_id == Document.doc_id)
            .join(InitiatingCountry,Subcategory.doc_id==InitiatingCountry.doc_id)
            .join(RecipientCountry,Subcategory.doc_id==RecipientCountry.doc_id)
            .join(Category,Category.doc_id==Document.doc_id)
            .filter(RecipientCountry.recipient_country.in_(cfg.recipients),
                    InitiatingCountry.initiating_country==country,
                    Category.category==category,
                    Subcategory.subcategory.in_(cfg.subcategories),
                    Document.date.between(start,end)).all())
    df = pd.DataFrame(metrics, columns=["subcategory", "num_docs"])
    df["subcategory"] = df["subcategory"].fillna("N/A")
    str_subcategory_metrics = df.to_markdown(index=False)
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_subcat_metrics.xlsx'),index=False)

    metrics = (db.session.query(
            func.date_trunc('week', Document.date).label("week_start"),
            func.count(func.distinct(Document.doc_id)).label("num_docs"))
        .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
        .join(Category,Category.doc_id==Document.doc_id)
        .filter(
            InitiatingCountry.initiating_country==country,
            Document.date.between(start, end),
            Category.category==category,
            RecipientCountry.recipient_country.in_(cfg.recipients)
        )
        .group_by("week_start")
        .order_by("week_start")
        .all()
    )
    df = pd.DataFrame(metrics, columns=["week_start", "num_docs"])
    df["week_start"] = df["week_start"].fillna("N/A")
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_WEEKLY_metrics.xlsx'),index=False)
    str_weekly_metrics = df.to_markdown(index=False)

    metrics = (db.session.query(
        func.date_trunc('week', Document.date).label("week_start"),
        func.count(func.distinct(Document.doc_id)).label("num_docs")
    )
    .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
    .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
    .join(Category,Category.doc_id==Document.doc_id)
    .filter(
        InitiatingCountry.initiating_country==country,
        Document.date > "2024-08-01",
        Document.date < end,
        Category.category==category,
        RecipientCountry.recipient_country.in_(cfg.recipients)
        )
        .group_by("week_start")
        .order_by("week_start")
        .all()
        )
    df = pd.DataFrame(metrics, columns=["week_start", "num_docs"])
    df["week_start"] = df["week_start"].fillna("N/A")
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_weeklyall_metrics.xlsx'),index=False)
    str_weekly_metrics_all = df.to_markdown(index=False)

    metrics = (db.session.query(
        func.date_trunc('month', Document.date).label("month_start"),
        func.count(func.distinct(Document.doc_id)).label("num_docs")
        )
        .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
        .join(Category,Category.doc_id==Document.doc_id)
        .filter(
            InitiatingCountry.initiating_country==country,
            Document.date > "2024-08-01",
            Document.date < end,
            Category.category==category,
            RecipientCountry.recipient_country.in_(cfg.recipients))
        .group_by("month_start")
        .order_by("month_start")
        .all())
    df = pd.DataFrame(metrics, columns=["month_start", "num_docs"])
    df["month_start"] = df["month_start"].fillna("N/A")
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_monthlyall_metrics.xlsx'),index=False)
    # docs_by_subcategory = df.to_markdown(index=False)
    str_monthly_metrics_all = df.to_markdown(index=False)
    metrics = (db.session.query(
        func.date_trunc('day', Document.date).label("day_published"),
        func.count(Document.doc_id).label("num_docs")
        )
        .join(RecipientCountry, RecipientCountry.doc_id == Document.doc_id)
        .join(InitiatingCountry, InitiatingCountry.doc_id == Document.doc_id)
        .filter(
            InitiatingCountry.initiating_country==country,
            Document.date.between(start, end),
            RecipientCountry.recipient_country.in_(cfg.recipients)
        )
        .group_by("day_published")
        .order_by("day_published")
        .all())
    df = pd.DataFrame(metrics, columns=["day", "num_docs"])
    df["day"] = df["day"].fillna(0)
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_daily_metrics.xlsx'),index=False)
    str_daily_metrics = df.to_markdown(index=False)
    event_metrics = (
    db.session.query(
        Event.event_name,
        func.count(EventSources.doc_id).label("num_docs"))
    .join(EventSources,EventSources.event_id==Event.id)
    .join(Document, EventSources.doc_id == Document.doc_id)
    .join(InitiatingCountry, Document.doc_id == InitiatingCountry.doc_id)
    .join(RecipientCountry, Document.doc_id == RecipientCountry.doc_id)
    .join(Category,Document.doc_id == Category.doc_id)
    .filter(InitiatingCountry.initiating_country==country,
        Document.date.between(start, end),
        Category.category==category,
        RecipientCountry.recipient_country.in_(cfg.recipients))
    .group_by(Event.event_name)
    .order_by(func.count(EventSources.doc_id).desc())
    .limit(20)  # This line limits the results to 20 rows
    .all())
    df = pd.DataFrame(event_metrics, columns=[f"event-{start} to {end}", "num_docs"])
    df[f"event-{start} to {end}"] = df[f"event-{start} to {end}"].fillna("N/A")
    if dataframe:
            df.to_excel(os.path.join(cfg.gai_data,f'{filename}_event_metrics.xlsx'),index=False)
    str_event_metrics = df.to_markdown(index=False)
    
    prompt = ''
    prompt += f'HISTORIC MONTHLY ARTICLE COUNTS:\n{str_monthly_metrics_all}\n\n'
    prompt += f'ARTICLE COUNTS BY COUNTRY:\n{str_metrics}\n\n'
    prompt += f'HISTORIC WEEKLY ARTICLE COUNTS:\n{str_weekly_metrics_all}\n\n'
    prompt += f'CURRENT WEEKLY ARTICLE COUNTS:\n{str_weekly_metrics}\n\n' 
    prompt += f'CURRENT MONTH RECIPIENT METRICS:\n{str_recipient_metrics}\n\n'
    prompt += f'CURRENT MONTH CATEGORY METRICS:\n{str_category_metrics}\n\n' 
    prompt += f'CURRENT MONTH SUBCATEGORY METRICS:\n{str_subcategory_metrics}\n\n' 
    prompt += f'CURRENT MONTH EVENT METRICS:\n{str_event_metrics}\n\n'
    prompt += f'CURRENT MONTH DAILY ARTICLE COUNTS BY DAY:n{str_daily_metrics}\n\n' 
  

    return prompt,str_metrics,str_recipient_metrics,str_category_metrics,str_subcategory_metrics,str_weekly_metrics,str_weekly_metrics_all,str_monthly_metrics_all,str_daily_metrics,str_event_metrics

def insert_summary(country, category, start_date, end_date, event_list, recipient=None, update=False):
    for event in event_list:
        if recipient:
            # Use upsert or do nothing based on `update`
            if update:
                stmt = insert(RecipientSummary).values(
                    country=country,
                    category=category,
                    start_date=start_date,
                    end_date=end_date,
                    recipient=recipient,
                    key_event=event['key_event'],
                    overview=event['overview'],
                    outcome=event['outcomes']
                ).on_conflict_do_update(
                    index_elements=['country', 'key_event', 'start_date', 'end_date', 'category', 'recipient'],
                    set_={
                        "overview": event['overview'],
                        "outcome": event['outcomes'],
                        # Add more fields to update if needed
                    }
                )
            else:
                stmt = insert(RecipientSummary).values(
                    country=country,
                    category=category,
                    start_date=start_date,
                    end_date=end_date,
                    recipient=recipient,
                    key_event=event['key_event'],
                    overview=event['overview'],
                    outcome=event['outcomes']
                ).on_conflict_do_nothing(
                    index_elements=['country', 'key_event', 'start_date', 'end_date', 'category', 'recipient']
                )
        else:
            if update:
                stmt = insert(CountrySummary).values(
                    country=country,
                    key_event=event['key_event'],
                    start_date=start_date,
                    end_date=end_date,
                    category=category,
                    overview=event['overview'],
                    outcome=event['outcomes']
                ).on_conflict_do_update(
                    index_elements=['country', 'key_event', 'start_date', 'end_date', 'category'],
                    set_={
                        "overview": event['overview'],
                        "outcome": event['outcomes'],
                    }
                )
            else:
                stmt = insert(CountrySummary).values(
                    country=country,
                    key_event=event['key_event'],
                    start_date=start_date,
                    end_date=end_date,
                    category=category,
                    overview=event['overview'],
                    outcome=event['outcomes']
                ).on_conflict_do_nothing(
                    index_elements=['country', 'key_event', 'start_date', 'end_date', 'category']
                )

        db.session.execute(stmt)
    db.session.commit()


import argparse
def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate daily soft power summaries with upsert behavior."
    )
    parser.add_argument(
        '--country',
        type=str,
        required=False,
        help='Initiating country (e.g., China)'
    )
    parser.add_argument(
        '--start_date',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD'
    )
    parser.add_argument(
        '--end_date',
        type=str,
        required=True,
        help='End date in YYYY-MM-DD'
    )
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    # process_dsr()
    # normalize_data()
    # flatten_event()
    # run_tokenize()
    from backend.app import app
    args = parse_args()
    with app.app_context():
        for country in cfg.influencers:
            daily_summaries(country,args.start_date,end_date=args.end_date)
            for category in cfg.categories:
                print(f'processing {category}...')
                stmt = (db.session.query(CountrySummary)
                        .filter(CountrySummary.country==country,
                                CountrySummary.start_date==args.start_date,
                                CountrySummary.end_date==args.end_date,
                                CountrySummary.category==category))
                summary_exists = db.session.query(stmt.exists()).scalar()
                if summary_exists:
                    print(f'Summary for {country} {category} from {start} to {end} already exists in the database.')
                    continue
                prompt,str_metrics,str_recipient_metrics,str_category_metrics,str_subcategory_metrics,str_weekly_metrics,str_weekly_metrics_all,str_monthly_metrics_all,str_daily_metrics,str_event_metrics = summary_metrics(country=country,start_date=args.start_date,end_date=args.end_date,category=category)
                reporting,str_reporting = summary_reporting(country=country,start_date=start,end_date=end,category=category)
                try:
                    activities,str_activities = summary_activities(country=country,start_date=start,end_date=end,category=category)
                except:
                    print('error processing activities')
                    str_activities=''
                try:
                    dailies,str_daily_metrics = summary_dailies(country=country,start_date=start,end_date=end,category=category)
                except:
                    print('error processing dailies')
                    str_daily_metrics = ''
                prompt += f'CURRENT MONTH DAILY SUMMARIES:\n{str_daily_metrics}\n\n'
                prompt += f'CURRENT MONTH Highlighted Activities:\n{str_activities}\n\n'
                prompt += f'CURRENT MONTH REPORTING:\n{str_reporting}\n\n'
                sys_prompt = gai_summary.format(country=country,category=category,start_date=start,end_date=end,date_string=today,top_n=8)
                response = gai(sys_prompt=sys_prompt,user_prompt=prompt)
                gai_output = fetch_gai_content(response)
                print('inserting summary')
                insert_summary(country=country,category=category,start_date=start,end_date=end,event_list=gai_output,update=False)