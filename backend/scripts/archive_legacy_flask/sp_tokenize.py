import pandas as pd
from backend.scripts.models import Document, TokenizedDocuments, SummarySources  # Add all required models
from backend.extensions import db
from sqlalchemy.dialects.postgresql import insert  # Add this import!
from concurrent.futures import ThreadPoolExecutor
import nltk
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
from nltk.tokenize import word_tokenize
from backend.app import app
from backend.extensions import db
from backend.scripts.models import Document, TokenizedDocuments
nltk.download('punkt_tab')
nltk.download('stopwords')
def preprocess(args):
    STOPWORDS = set(stopwords.words('english'))
    STEMMER = PorterStemmer()
    doc_id, text = args  # unpack tuple
    tokens = word_tokenize(text.lower())
    filtered_tokens = [word for word in tokens if word not in STOPWORDS]
    stemmed_tokens = [STEMMER.stem(word) for word in filtered_tokens]
    # Open a session within the thread context
    td = TokenizedDocuments(
        doc_id = doc_id,
        tokens = " ".join(stemmed_tokens)
    )
    db.session.add(td)
    print(f'processed {doc_id}')

def run_tokenize(batch_size=500):

    with app.app_context():
        token_subq = db.session.query(
            TokenizedDocuments.doc_id
        ).subquery()

        q = (
            db.session.query(
                Document.doc_id,
                Document.title,
                Document.distilled_text
            )
            .outerjoin(token_subq, Document.doc_id == token_subq.c.doc_id)
            .filter(token_subq.c.doc_id.is_(None))
            .yield_per(batch_size)
        )

        for doc_id, title, distilled in q:
            # should only add to session, not commit
            preprocess((doc_id, f"{title} {distilled}"))

        # single commit at the end
        db.session.commit()

if __name__ == '__main__':
    run_tokenize()