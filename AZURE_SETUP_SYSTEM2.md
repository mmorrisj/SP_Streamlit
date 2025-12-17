# Azure OpenAI Setup for System 2

## Overview

System 2 now supports Azure OpenAI via the unified `gai()` function with two credential modes:

1. **AWS Secrets Manager Mode (Default/Production)** - Uses boto3 + config.yaml
2. **Environment Variables Mode (Optional/Testing)** - Uses .env file

---

## What Was Updated

### Files Modified

1. **[shared/utils/utils.py](shared/utils/utils.py)**
   - ✅ Uncommented Azure and boto3 imports (lines 9-12)
   - ✅ Added `get_db_secret()` function for fetching specific secrets
   - ✅ Updated `initialize_client()` to support both credential modes
   - ✅ Updated `gai()` function to support `source` parameter:
     - `source="azure"` - Azure OpenAI (System 2 default)
     - `source="proxy"` - FastAPI proxy → OpenAI (System 1)
     - `source="openai"` - Direct OpenAI API

2. **[test_azure_connection.ipynb](test_azure_connection.ipynb)**
   - ✅ Created comprehensive test suite for both credential modes
   - ✅ Tests configuration, secret fetching, client initialization, and LLM calls

---

## Configuration Required

### AWS Secrets Manager Mode (Default)

#### 1. config.yaml Setup
Ensure `shared/config/config.yaml` has the following:

```yaml
aws:
  secret_name: "azure-openai-main"  # Your secret name in AWS Secrets Manager
  region_name: "us-east-1"          # Your AWS region
  api_version: "2024-02-15-preview" # Azure API version
```

#### 2. AWS Credentials
Set these environment variables for boto3:

```bash
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
```

#### 3. AWS Secrets Manager Secret
Create a secret in AWS Secrets Manager with this JSON format:

```json
{
  "endpoint": "https://your-resource.openai.azure.com/",
  "key": "your_azure_openai_api_key",
  "deployment_name": "gpt-4o-mini",  # Optional
  "GPT_4_1_DEPLOYMENT_NAME": "gpt-4" # Optional
}
```

**What Happens**:
- `gai()` calls `initialize_client(use_env_vars=False)`
- `initialize_client()` calls `get_secret()`
- `get_secret()` uses boto3 to fetch credentials from AWS Secrets Manager
- Azure credentials extracted and client created

**NO Azure environment variables needed!**

---

### Environment Variables Mode (Optional)

Add these to your `.env` file:

```bash
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
```

---

## Usage Examples

### Azure OpenAI (AWS Secrets Manager Mode - RECOMMENDED)

```python
from shared.utils.utils import gai

# Default: Uses AWS Secrets Manager via boto3
response = gai(
    sys_prompt="You are a helpful assistant.",
    user_prompt="Explain the Belt and Road Initiative.",
    model="gpt-4o-mini",
    source="azure"  # Uses boto3 + AWS Secrets Manager automatically
)
```

### Azure OpenAI (Environment Variables Mode)

```python
response = gai(
    sys_prompt="You are a helpful assistant.",
    user_prompt="Explain the Belt and Road Initiative.",
    model="gpt-4o-mini",
    source="azure",
    azure_use_env=True  # Use .env variables instead
)
```

### FastAPI Proxy (System 1)

```python
response = gai(
    sys_prompt="You are a helpful assistant.",
    user_prompt="Explain the Belt and Road Initiative.",
    model="gpt-4o-mini",
    source="proxy"  # Routes through FastAPI → OpenAI
)
```

### Direct OpenAI API

```python
response = gai(
    sys_prompt="You are a helpful assistant.",
    user_prompt="Explain the Belt and Road Initiative.",
    model="gpt-4o-mini",
    source="openai"  # Requires OPENAI_PROJ_API env var
)
```

---

## Testing on System 2

### Step 1: Test Azure Connection

Run the test notebook:

```bash
jupyter notebook test_azure_connection.ipynb
```

Set the credential mode in Cell 1:

```python
CREDENTIAL_MODE = "secrets"  # For AWS Secrets Manager (default)
# CREDENTIAL_MODE = "env"     # For environment variables
```

Run all cells. You should see:
- ✅ TEST 1 PASSED: Configuration check
- ✅ TEST 2 PASSED: Secret fetched from AWS Secrets Manager
- ✅ TEST 3 PASSED: Client initialization
- ✅ TEST 4 PASSED: Simple LLM call
- ✅ TEST 5 PASSED: JSON response parsing
- ✅ TEST 6 PASSED: Materiality scoring format

### Step 2: Update Pipeline Scripts

For any script that needs to use Azure OpenAI on System 2, update the `gai()` calls:

**Before**:
```python
response = gai(sys_prompt, user_prompt, model="gpt-4o-mini")  # Uses proxy by default
```

**After (System 2 with AWS Secrets Manager)**:
```python
response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", source="azure")
```

**After (System 2 with env vars)**:
```python
response = gai(sys_prompt, user_prompt, model="gpt-4o-mini", source="azure", azure_use_env=True)
```

---

## Backward Compatibility

The `use_proxy` parameter is still supported for backward compatibility:

```python
# Old style (still works)
response = gai(sys_prompt, user_prompt, use_proxy=True)   # Same as source="proxy"
response = gai(sys_prompt, user_prompt, use_proxy=False)  # Same as source="openai"

# New style (recommended)
response = gai(sys_prompt, user_prompt, source="proxy")
response = gai(sys_prompt, user_prompt, source="azure")
```

---

## Troubleshooting

### AWS Secrets Manager Mode Issues

**Error: "No module named 'boto3'"**
```bash
pip install boto3
```

**Error: "ClientError: Secrets Manager can't find the specified secret"**
- Check `cfg.aws['secret_name']` in config.yaml matches the secret name in AWS Secrets Manager
- Verify the secret exists in the correct AWS region

**Error: "Unable to locate credentials"**
- Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
- Or configure AWS CLI: `aws configure`

**Error: "Secret missing 'endpoint' or 'key' fields"**
- Verify secret JSON format:
  ```json
  {
    "endpoint": "https://your-resource.openai.azure.com/",
    "key": "your_api_key"
  }
  ```

### Environment Variables Mode Issues

**Error: "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set"**
- Add to `.env` file:
  ```
  AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
  AZURE_OPENAI_API_KEY=your_api_key
  ```

---

## Next Steps

1. ✅ Run `test_azure_connection.ipynb` on System 2
2. ✅ Verify all 6 tests pass
3. ✅ Update pipeline scripts to use `source="azure"`
4. ✅ Test materiality scoring pipeline
5. ✅ Test summary generation pipeline

Once testing passes, System 2 will be ready for production Azure OpenAI usage!
