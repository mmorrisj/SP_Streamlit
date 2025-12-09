"""
Temporary script to create entity tables.
"""
from shared.database.database import DatabaseManager
from shared.models.models_entity import Base

def main():
    # Create database manager
    db_manager = DatabaseManager()

    # Get engine property
    engine = db_manager.engine

    # Create all tables defined in models_entity
    Base.metadata.create_all(engine)

    print("[OK] Entity tables created successfully!")
    print("   - entities")
    print("   - document_entities")
    print("   - entity_relationships")
    print("   - entity_extraction_runs")

if __name__ == "__main__":
    main()
