#!/bin/bash
# Upload batch file from Docker container (bypasses Windows SSL issues)

BATCH_FILE="$1"
API_KEY="$2"

if [ -z "$BATCH_FILE" ] || [ -z "$API_KEY" ]; then
    echo "Usage: ./upload_from_docker.sh <batch_file> <api_key>"
    exit 1
fi

if [ ! -f "$BATCH_FILE" ]; then
    echo "Error: File not found: $BATCH_FILE"
    exit 1
fi

FILE_SIZE=$(du -h "$BATCH_FILE" | cut -f1)
echo "Uploading: $BATCH_FILE"
echo "File size: $FILE_SIZE"
echo ""

echo "Uploading via curl from Docker (uses Linux SSL, bypasses Windows Schannel)..."
curl --http1.1 \
     --tlsv1.2 \
     https://api.openai.com/v1/files \
     -H "Authorization: Bearer $API_KEY" \
     -F "file=@$BATCH_FILE" \
     -F "purpose=batch" \
     --max-time 600 \
     --connect-timeout 60

echo ""
echo "Done!"
