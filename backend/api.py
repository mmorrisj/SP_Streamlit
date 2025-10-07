from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import boto3
from botocore.exceptions import ClientError
from typing import Optional, List
from backend.scripts.utils import gai, fetch_gai_content, fetch_gai_response
app = FastAPI(title="SoftPower Backend API")

# S3 client (will use host's IAM role/credentials)
s3_client = boto3.client('s3')

# Request/Response models
class S3DownloadRequest(BaseModel):
    bucket: str
    key: str

class S3ListRequest(BaseModel):
    bucket: str
    prefix: Optional[str] = ""
    max_keys: Optional[int] = 1000

class S3FileInfo(BaseModel):
    key: str
    size: int
    last_modified: str

class QueryInput(BaseModel):
    model: str = "gpt-4.1"
    sys_prompt: str
    prompt: str

@app.post("/query")
def query_gai(input: QueryInput):
    response = gai(sys_prompt='',user_prompt=input.prompt,model=input.model)
    return fetch_gai_content(response)

@app.post("/material_query")
def material_gai_query(input: QueryInput):
    content = gai(input.sys_prompt, input.prompt, input.model)
    # If B returns string or C returns dict, either:
    return {"response": content}

@app.get("/")
async def root():
    return {"message": "SoftPower Backend API is running"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ml-backend",
        "db_host": os.getenv('DB_HOST', 'not configured')
    }

@app.post("/s3/download")
async def download_s3_file(request: S3DownloadRequest):
    """Download file from S3 and return content"""
    try:
        response = s3_client.get_object(Bucket=request.bucket, Key=request.key)
        content = response['Body'].read()
        return {
            "bucket": request.bucket,
            "key": request.key,
            "size": len(content),
            "content": content.decode('utf-8') if request.key.endswith(('.txt', '.json', '.csv')) else None,
            "content_type": response['ContentType']
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.post("/s3/list")
async def list_s3_files(request: S3ListRequest):
    """List files in S3 bucket with optional prefix"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=request.bucket,
            Prefix=request.prefix,
            MaxKeys=request.max_keys
        )
        
        files = []
        for obj in response.get('Contents', []):
            files.append({
                "key": obj['Key'],
                "size": obj['Size'],
                "last_modified": obj['LastModified'].isoformat()
            })
        
        return {
            "bucket": request.bucket,
            "prefix": request.prefix,
            "count": len(files),
            "files": files
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")

@app.get("/s3/download-to-file")
async def download_s3_to_file(bucket: str, key: str, local_path: str):
    """Download S3 file directly to a local path"""
    try:
        s3_client.download_file(bucket, key, local_path)
        return {
            "bucket": bucket,
            "key": key,
            "local_path": local_path,
            "status": "downloaded"
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 error: {str(e)}")


class S3UploadRequest(BaseModel):
    bucket: str
    key: str
    content: str

@app.post("/s3/upload")
async def upload_s3_content(request: S3UploadRequest):
    """Upload content to S3"""
    try:
        s3_client.put_object(
            Bucket=request.bucket,
            Key=request.key,
            Body=request.content.encode('utf-8'),
            ContentType='application/json'
        )
        return {
            "bucket": request.bucket,
            "key": request.key,
            "status": "uploaded"
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"S3 error: {str(e)}")