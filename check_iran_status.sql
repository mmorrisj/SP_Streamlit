-- Check Iran entity extraction status

-- Total Iran documents on 2025-06-01
SELECT 'Total Iran docs on 2025-06-01' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
WHERE ic.initiating_country = 'Iran'
  AND d.date = '2025-06-01';

-- Iran docs with entities on 2025-06-01
SELECT 'Docs WITH entities on 2025-06-01' as metric, COUNT(DISTINCT re.doc_id) as count
FROM raw_entities re
JOIN documents d ON re.doc_id = d.doc_id
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
WHERE ic.initiating_country = 'Iran'
  AND d.date = '2025-06-01';

-- Iran docs WITHOUT entities on 2025-06-01
SELECT 'Docs WITHOUT entities on 2025-06-01' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
LEFT JOIN raw_entities re ON d.doc_id = re.doc_id
WHERE ic.initiating_country = 'Iran'
  AND d.date = '2025-06-01'
  AND re.doc_id IS NULL;

-- Sample doc_ids without entities
SELECT 'Sample doc_ids WITHOUT entities:' as info, d.doc_id
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
LEFT JOIN raw_entities re ON d.doc_id = re.doc_id
WHERE ic.initiating_country = 'Iran'
  AND d.date = '2025-06-01'
  AND re.doc_id IS NULL
LIMIT 10;
