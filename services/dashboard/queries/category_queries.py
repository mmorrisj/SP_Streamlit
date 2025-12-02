"""
Query functions for category summaries (country-level and bilateral).
"""

from typing import List, Dict, Optional
from datetime import date
from sqlalchemy import text
from shared.database.database import get_session
from shared.models.models import CountryCategorySummary, BilateralCategorySummary


# ============================================================================
# Country Category Summary Queries
# ============================================================================

def get_all_country_category_summaries() -> List[Dict]:
    """Get all country category summaries."""
    with get_session() as session:
        summaries = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.is_deleted == False
        ).all()

        return [country_category_to_dict(s) for s in summaries]


def get_country_category_summary(country: str, category: str) -> Optional[Dict]:
    """
    Get a specific country category summary.

    Args:
        country: Initiating country name
        category: Category name (Economic, Social, Military, Diplomacy)

    Returns:
        Summary dict or None if not found
    """
    with get_session() as session:
        summary = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.initiating_country == country,
            CountryCategorySummary.category == category,
            CountryCategorySummary.is_deleted == False
        ).first()

        if summary:
            return country_category_to_dict(summary)
        return None


def get_country_categories(country: str) -> List[Dict]:
    """Get all category summaries for a specific country."""
    with get_session() as session:
        summaries = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.initiating_country == country,
            CountryCategorySummary.is_deleted == False
        ).order_by(
            CountryCategorySummary.total_documents.desc()
        ).all()

        return [country_category_to_dict(s) for s in summaries]


def get_category_by_countries(category: str) -> List[Dict]:
    """Get all countries using a specific category."""
    with get_session() as session:
        summaries = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.category == category,
            CountryCategorySummary.is_deleted == False
        ).order_by(
            CountryCategorySummary.total_documents.desc()
        ).all()

        return [country_category_to_dict(s) for s in summaries]


def get_top_country_categories_by_documents(limit: int = 20) -> List[Dict]:
    """Get top country-category combinations by document count."""
    with get_session() as session:
        summaries = session.query(CountryCategorySummary).filter(
            CountryCategorySummary.is_deleted == False
        ).order_by(
            CountryCategorySummary.total_documents.desc()
        ).limit(limit).all()

        return [country_category_to_dict(s) for s in summaries]


def get_country_category_statistics() -> Dict:
    """Get aggregate statistics about country category summaries."""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                COUNT(*) as total_summaries,
                COUNT(DISTINCT initiating_country) as unique_countries,
                COUNT(DISTINCT category) as unique_categories,
                SUM(total_documents) as total_documents,
                AVG(material_score_avg) as avg_material_score,
                MAX(material_score_avg) as max_material_score,
                MIN(material_score_avg) as min_material_score
            FROM country_category_summaries
            WHERE is_deleted = FALSE
        """)).fetchone()

        return {
            'total_summaries': result[0],
            'unique_countries': result[1],
            'unique_categories': result[2],
            'total_documents': result[3],
            'avg_material_score': float(result[4]) if result[4] else 0,
            'max_material_score': float(result[5]) if result[5] else 0,
            'min_material_score': float(result[6]) if result[6] else 0
        }


# ============================================================================
# Bilateral Category Summary Queries
# ============================================================================

def get_all_bilateral_category_summaries() -> List[Dict]:
    """Get all bilateral category summaries."""
    with get_session() as session:
        summaries = session.query(BilateralCategorySummary).filter(
            BilateralCategorySummary.is_deleted == False
        ).all()

        return [bilateral_category_to_dict(s) for s in summaries]


def get_bilateral_category_summary(
    initiating_country: str,
    recipient_country: str,
    category: str
) -> Optional[Dict]:
    """
    Get a specific bilateral category summary.

    Args:
        initiating_country: Initiating country name
        recipient_country: Recipient country name
        category: Category name

    Returns:
        Summary dict or None if not found
    """
    with get_session() as session:
        summary = session.query(BilateralCategorySummary).filter(
            BilateralCategorySummary.initiating_country == initiating_country,
            BilateralCategorySummary.recipient_country == recipient_country,
            BilateralCategorySummary.category == category,
            BilateralCategorySummary.is_deleted == False
        ).first()

        if summary:
            return bilateral_category_to_dict(summary)
        return None


def get_bilateral_categories(
    initiating_country: str,
    recipient_country: str
) -> List[Dict]:
    """Get all category summaries for a specific bilateral pair."""
    with get_session() as session:
        summaries = session.query(BilateralCategorySummary).filter(
            BilateralCategorySummary.initiating_country == initiating_country,
            BilateralCategorySummary.recipient_country == recipient_country,
            BilateralCategorySummary.is_deleted == False
        ).order_by(
            BilateralCategorySummary.total_documents.desc()
        ).all()

        return [bilateral_category_to_dict(s) for s in summaries]


def get_top_bilateral_categories_by_documents(limit: int = 20) -> List[Dict]:
    """Get top bilateral-category combinations by document count."""
    with get_session() as session:
        summaries = session.query(BilateralCategorySummary).filter(
            BilateralCategorySummary.is_deleted == False
        ).order_by(
            BilateralCategorySummary.total_documents.desc()
        ).limit(limit).all()

        return [bilateral_category_to_dict(s) for s in summaries]


def get_bilateral_category_statistics() -> Dict:
    """Get aggregate statistics about bilateral category summaries."""
    with get_session() as session:
        result = session.execute(text("""
            SELECT
                COUNT(*) as total_summaries,
                COUNT(DISTINCT initiating_country) as unique_initiators,
                COUNT(DISTINCT recipient_country) as unique_recipients,
                COUNT(DISTINCT category) as unique_categories,
                SUM(total_documents) as total_documents,
                AVG(material_score_avg) as avg_material_score
            FROM bilateral_category_summaries
            WHERE is_deleted = FALSE
        """)).fetchone()

        return {
            'total_summaries': result[0],
            'unique_initiators': result[1],
            'unique_recipients': result[2],
            'unique_categories': result[3],
            'total_documents': result[4],
            'avg_material_score': float(result[5]) if result[5] else 0
        }


# ============================================================================
# Conversion Functions
# ============================================================================

def country_category_to_dict(summary: CountryCategorySummary) -> Dict:
    """Convert a CountryCategorySummary ORM object to a dict."""
    return {
        'id': str(summary.id),
        'initiating_country': summary.initiating_country,
        'category': summary.category,
        'first_interaction_date': summary.first_interaction_date,
        'last_interaction_date': summary.last_interaction_date,
        'analysis_generated_at': summary.analysis_generated_at,
        'total_documents': summary.total_documents,
        'total_daily_events': summary.total_daily_events,
        'total_weekly_events': summary.total_weekly_events,
        'total_monthly_events': summary.total_monthly_events,
        'count_by_recipient': summary.count_by_recipient,
        'count_by_subcategory': summary.count_by_subcategory,
        'count_by_source': summary.count_by_source,
        'activity_by_month': summary.activity_by_month,
        'category_summary': summary.category_summary,
        'material_score_histogram': summary.material_score_histogram,
        'material_score_avg': summary.material_score_avg,
        'material_score_median': summary.material_score_median,
        'material_score': summary.material_score,
        'material_justification': summary.material_justification,
        'created_at': summary.created_at,
        'updated_at': summary.updated_at,
        'created_by': summary.created_by,
        'version': summary.version,
        'is_deleted': summary.is_deleted,
        'deleted_at': summary.deleted_at
    }


def bilateral_category_to_dict(summary: BilateralCategorySummary) -> Dict:
    """Convert a BilateralCategorySummary ORM object to a dict."""
    return {
        'id': str(summary.id),
        'initiating_country': summary.initiating_country,
        'recipient_country': summary.recipient_country,
        'category': summary.category,
        'first_interaction_date': summary.first_interaction_date,
        'last_interaction_date': summary.last_interaction_date,
        'analysis_generated_at': summary.analysis_generated_at,
        'total_documents': summary.total_documents,
        'total_daily_events': summary.total_daily_events,
        'total_weekly_events': summary.total_weekly_events,
        'total_monthly_events': summary.total_monthly_events,
        'count_by_subcategory': summary.count_by_subcategory,
        'count_by_source': summary.count_by_source,
        'activity_by_month': summary.activity_by_month,
        'category_summary': summary.category_summary,
        'material_score_histogram': summary.material_score_histogram,
        'material_score_avg': summary.material_score_avg,
        'material_score_median': summary.material_score_median,
        'material_score': summary.material_score,
        'material_justification': summary.material_justification,
        'created_at': summary.created_at,
        'updated_at': summary.updated_at,
        'created_by': summary.created_by,
        'version': summary.version,
        'is_deleted': summary.is_deleted,
        'deleted_at': summary.deleted_at
    }
