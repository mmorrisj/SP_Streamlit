"""
Script to update all import statements to the new directory structure.
"""
import os
import re
from pathlib import Path

# Define import mapping (old -> new)
IMPORT_MAPPINGS = {
    'from backend.database import': 'from shared.database.database import',
    'from backend.models import': 'from shared.models.models import',
    'from backend.config import': 'from shared.config.config import',
    'from backend.scripts.utils import': 'from shared.utils.utils import',
    'from backend.scripts.prompts import': 'from shared.utils.prompts import',
    'from backend.api_client import': 'from services.api.api_client import',
    'from backend.api import': 'from services.api.main import',
    'from backend.routes import': 'from services.api.routes import',
    'from backend.commands import': 'from services.api.commands import',
    'from backend.scripts.s3 import': 'from services.pipeline.embeddings.s3 import',
    'from backend.scripts.embedding_vectorstore import': 'from services.pipeline.embeddings.embedding_vectorstore import',
    'from backend.scripts.embedding_dispatcher import': 'from services.pipeline.embeddings.embedding_dispatcher import',

    # Import statements without 'from'
    'import backend.database': 'import shared.database.database',
    'import backend.models': 'import shared.models.models',
    'import backend.config': 'import shared.config.config',
}

def update_file_imports(file_path: Path):
    """Update imports in a single file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # Apply all mappings
        for old_import, new_import in IMPORT_MAPPINGS.items():
            content = content.replace(old_import, new_import)

        # Only write if content changed
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"[+] Updated: {file_path}")
            return True
        return False
    except Exception as e:
        print(f"[!] Error updating {file_path}: {e}")
        return False

def update_all_imports():
    """Update imports in all Python files in the new structure."""
    directories = [
        'services/pipeline',
        'services/api',
        'services/dashboard',
        'shared',
    ]

    updated_count = 0
    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob('*.py'):
            if update_file_imports(py_file):
                updated_count += 1

    print(f"\n[+] Updated {updated_count} files")

if __name__ == "__main__":
    print("Updating import statements to new directory structure...\n")
    update_all_imports()
    print("\n[+] Done!")
