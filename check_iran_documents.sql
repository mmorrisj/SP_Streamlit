-- Check Iran document filtering issues

-- Total Iran documents (current query)
SELECT 'Total Iran documents (current)' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
WHERE ic.initiating_country = 'Iran';

-- Iran documents with Iran as recipient (should be excluded)
SELECT 'Iran-Iran documents (self-referential)' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
JOIN recipient_countries rc ON d.doc_id = rc.doc_id
WHERE ic.initiating_country = 'Iran'
  AND rc.recipient_country = 'Iran';

-- Iran documents with valid recipients only (from config.yaml)
SELECT 'Iran docs with valid recipients' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
JOIN recipient_countries rc ON d.doc_id = rc.doc_id
WHERE ic.initiating_country = 'Iran'
  AND rc.recipient_country IN (
    'Bahrain', 'Cyprus', 'Egypt', 'Iraq', 'Israel', 'Jordan',
    'Kuwait', 'Lebanon', 'Libya', 'Oman', 'Palestine', 'Qatar',
    'Saudi Arabia', 'Syria', 'Turkey', 'United Arab Emirates', 'UAE', 'Yemen'
  )
  AND rc.recipient_country != 'Iran';

-- Iran documents with NO recipients
SELECT 'Iran docs with NO recipients' as metric, COUNT(DISTINCT d.doc_id) as count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
LEFT JOIN recipient_countries rc ON d.doc_id = rc.doc_id
WHERE ic.initiating_country = 'Iran'
  AND rc.doc_id IS NULL;

-- Breakdown by recipient country
SELECT 'Breakdown by recipient:' as info,
       rc.recipient_country,
       COUNT(DISTINCT d.doc_id) as doc_count
FROM documents d
JOIN initiating_countries ic ON d.doc_id = ic.doc_id
LEFT JOIN recipient_countries rc ON d.doc_id = rc.doc_id
WHERE ic.initiating_country = 'Iran'
GROUP BY rc.recipient_country
ORDER BY doc_count DESC
LIMIT 20;
