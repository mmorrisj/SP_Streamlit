# 🎯 API Filtering Update - Summary

## What Was Changed

All API endpoints now filter data based on the `config.yaml` file to show only:
- **Influencers** (initiating countries): China, Russia, Iran, Turkey, United States
- **Recipients** (recipient countries): Listed in config.yaml
- **Excluding same-country relationships**: (e.g., Iran → Iran)

## Updated Endpoints

### 1. `/api/documents/stats` (Dashboard Statistics)
**Filters Applied:**
- ✅ Only influencers as initiating countries
- ✅ Only recipients as recipient countries
- ✅ Excludes same-country pairs (Iran-Iran, etc.)
- ✅ Uses normalized tables (`InitiatingCountry`, `RecipientCountry`, `Category`)

**What You'll See:**
- Document counts filtered to influencer → recipient relationships
- "Top Countries" chart shows only the 5 influencers
- Week-by-week trends for filtered data only

---

### 2. `/api/documents` (Documents List)
**Filters Applied:**
- Same filtering as stats endpoint
- Returns documents where initiating_country ∈ INFLUENCERS
- And recipient_country ∈ RECIPIENTS
- And initiating_country ≠ recipient_country

**What You'll See:**
- Only documents representing influence activities between influencers and recipients
- No domestic activities (Iran-Iran, Turkey-Turkey, etc.)

---

### 3. `/api/bilateral` (Bilateral Relationships)
**Filters Applied:**
- ✅ Only influencers → recipients pairs
- ✅ **Excludes same-country** (Iran-Iran)
- ✅ Uses normalized tables for accuracy

**What You'll See:**
- Top 30 bilateral relationships
- Examples: China → Egypt, Iran → Iraq, Russia → Syria
- **Will NOT show**: Iran → Iran, Turkey → Turkey, etc.

---

### 4. `/api/categories` (Category Distribution)
**Filters Applied:**
- Categories aggregated from filtered documents only
- Uses same influencer/recipient filtering

**What You'll See:**
- Category breakdown (Diplomacy, Social, Economic, etc.)
- Only counts documents matching influencer → recipient criteria

---

### 5. `/api/filters` (Filter Options)
**Changed:**
- **Countries dropdown**: Returns only INFLUENCERS from config (not all DB countries)
- **Categories/Subcategories**: From filtered data only
- **Date range**: From filtered data only

**What You'll See:**
- Country filter shows: China, Iran, Russia, Turkey, United States
- Not the full list of 100+ countries in the database

---

## Config.yaml Integration

```yaml
influencers:
  - China
  - Russia
  - Iran
  - Turkey
  - United States

recipients:
  - Bahrain
  - Cyprus
  - Egypt
  - Iran        # Can be both influencer AND recipient
  - Iraq
  - Israel
  - Jordan
  - Kuwait
  - Lebanon
  - Libya
  - Oman
  - Palestine
  - Qatar
  - Saudi Arabia
  - Syria
  - Turkey      # Can be both influencer AND recipient
  - United Arab Emirates
  - UAE
  - Yemen
```

**Note:** Iran and Turkey appear in both lists - they can be both influencers and recipients, but we exclude self-relationships (Iran-Iran, Turkey-Turkey).

---

## Before vs After

### Before (Old API):
```
Total Documents: 496,783
Top Countries: Iran (174,501), China (38,204), United States (36,598), Turkey (25,235)...
Bilateral: Includes ALL country pairs, including domestic (Iran-Iran: 50,000)
```

### After (New API with Filtering):
```
Total Documents: ~[filtered count]
Top Countries: Only the 5 influencers
Bilateral: Only cross-border influencer → recipient pairs
No Iran-Iran, Turkey-Turkey, etc.
```

---

## Technical Implementation

### Normalized Tables Used:
- `initiating_countries` (many-to-many with documents)
- `recipient_countries` (many-to-many with documents)
- `categories` (many-to-many with documents)
- `subcategories` (many-to-many with documents)

### SQL Pattern:
```python
session.query(...).join(
    InitiatingCountry
).join(
    RecipientCountry,
    RecipientCountry.doc_id == Document.doc_id
).filter(
    InitiatingCountry.initiating_country.in_(INFLUENCERS),
    RecipientCountry.recipient_country.in_(RECIPIENTS),
    InitiatingCountry.initiating_country != RecipientCountry.recipient_country
)
```

---

## Benefits

1. **Focused Analysis**: Only see relevant influencer-recipient relationships
2. **Excludes Noise**: Domestic activities (Iran-Iran) filtered out
3. **Config-Driven**: Easy to update influencers/recipients in config.yaml
4. **Normalized Data**: Accurate counts using proper database relationships
5. **Performance**: Indexed joins on normalized tables

---

## Testing

To verify filtering is working:

```bash
# 1. Restart Docker Desktop

# 2. Start database
docker-compose up -d db

# 3. Check config is loaded
curl http://localhost:8000/api/filters
# Should show only 5 countries: China, Iran, Russia, Turkey, United States

# 4. Check bilateral excludes same-country
curl http://localhost:8000/api/bilateral
# Should NOT contain Iran-Iran, Turkey-Turkey, etc.

# 5. Check stats
curl http://localhost:8000/api/documents/stats
# Total should be much less than 496,783
```

---

## Updating Filters

To change which countries are tracked:

**Edit `config.yaml`:**
```yaml
influencers:
  - Add new country here

recipients:
  - Add new recipient here
```

**Restart API server:**
```bash
# Kill old server
taskkill //F //PID [pid]

# Start new server
cd server
python main.py
```

The changes will be picked up immediately!

---

## Summary

✅ **All endpoints** now filter by influencers → recipients
✅ **Same-country pairs** excluded (Iran-Iran, etc.)
✅ **Config-driven** - easy to update
✅ **Normalized tables** - accurate data
✅ **React UI** will automatically show filtered data

The dashboard now focuses on cross-border influence activities only, excluding domestic relationships!
