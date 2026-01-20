"""
Check what hyperlinks are actually stored in the Word document
"""

from docx import Document
from pathlib import Path

# Get the most recent summary document
output_dir = Path(__file__).parent / "output"
files = sorted(output_dir.glob("China_*_Summary_*.docx"), key=lambda x: x.stat().st_mtime, reverse=True)

if not files:
    print("No summary documents found")
    exit(1)

latest_doc = files[0]
print(f"Checking: {latest_doc.name}\n")

doc = Document(latest_doc)

# Extract hyperlinks from document
hyperlink_count = 0
for para in doc.paragraphs:
    # Check for hyperlinks in the paragraph's XML
    for hyperlink in para._element.xpath('.//w:hyperlink'):
        hyperlink_count += 1
        # Get the relationship ID
        r_id = hyperlink.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')

        if r_id:
            # Get the actual URL from the relationships
            rels = para.part.rels
            if r_id in rels:
                url = rels[r_id].target_ref

                # Get the display text
                text_elements = hyperlink.xpath('.//w:t')
                display_text = ''.join(t.text for t in text_elements if t.text)

                print(f"Link #{hyperlink_count}")
                print(f"  Text: {display_text}")
                print(f"  URL: {url[:150]}...")

                # Parse the URL to check for doc IDs
                if 'id:(' in url or 'id%3A(' in url:
                    # Extract the ID portion
                    if 'id:(' in url:
                        id_part = url.split('id:(')[1].split(')')[0]
                    else:
                        id_part = url.split('id%3A(')[1].split(')')[0]

                    # Count IDs
                    ids = [x.strip().strip('"') for x in id_part.split(' OR ') if x.strip()]
                    print(f"  Number of IDs: {len(ids)}")
                    print(f"  First 3 IDs: {ids[:3]}")

                print()

                if hyperlink_count >= 5:
                    print("(Showing first 5 hyperlinks only)")
                    break

        if hyperlink_count >= 5:
            break

    if hyperlink_count >= 5:
        break

if hyperlink_count == 0:
    print("No hyperlinks found in document!")
else:
    print(f"\nTotal hyperlinks checked: {min(hyperlink_count, 5)}")
