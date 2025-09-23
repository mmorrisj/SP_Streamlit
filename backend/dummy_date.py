# create 100 samples of dummy date data for testing 
# inputs are start_date and end_date in 'YYYY-MM-DD' format
# module uses random dates to generate dates between the two inputs
# uses uuid as doc_id
# hits opena api to generate synthetic inputs for following json:
'''class Document(Base):
    """
    Core document model - converted from Flask-SQLAlchemy to pure SQLAlchemy.
    
    Changes made:
    - Replaced db.Model with Base
    - Added type hints with Mapped[]
    - Used mapped_column() instead of db.Column()
    - Added proper __repr__ method
    - Added relationship to Salience
    """
    __tablename__ = 'documents'
    
    # Primary key
    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    
    # Core document metadata  
    title: Mapped[Optional[str]] = mapped_column(Text)
    source_name: Mapped[Optional[str]] = mapped_column(Text)
    source_geofocus: Mapped[Optional[str]] = mapped_column(Text)
    source_consumption: Mapped[Optional[str]] = mapped_column(Text)
    source_description: Mapped[Optional[str]] = mapped_column(Text)
    source_medium: Mapped[Optional[str]] = mapped_column(Text)
    source_location: Mapped[Optional[str]] = mapped_column(Text)
    source_editorial: Mapped[Optional[str]] = mapped_column(Text)
    
    # Temporal data
    date: Mapped[Optional[date]] = mapped_column(Date)
    
    # Processing metadata
    collection_name: Mapped[Optional[str]] = mapped_column(Text)
    gai_engine: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptid: Mapped[Optional[str]] = mapped_column(Text)
    gai_promptversion: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Analysis results 
    salience: Mapped[Optional[str]] = mapped_column(Text)
    salience_justification: Mapped[Optional[str]] = mapped_column(Text)
    salience_bool: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    category_justification: Mapped[Optional[str]] = mapped_column(Text)
    subcategory: Mapped[Optional[str]] = mapped_column(Text)
    
    # Geographic and relational data
    initiating_country: Mapped[Optional[str]] = mapped_column(Text)
    recipient_country: Mapped[Optional[str]] = mapped_column(Text)
    projects: Mapped[Optional[str]] = mapped_column(Text)
    lat_long: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    
    # Financial data
    monetary_commitment: Mapped[Optional[str]] = mapped_column(Text)
    
    # Content
    distilled_text: Mapped[Optional[str]] = mapped_column(Text)
    event_name: Mapped[Optional[str]] = mapped_column(Text)
    '''
import random
from datetime import datetime, timedelta
import uuid
import openai
import os
import json
from typing import List, Dict, Any  
from dotenv import load_dotenv
load_dotenv()

