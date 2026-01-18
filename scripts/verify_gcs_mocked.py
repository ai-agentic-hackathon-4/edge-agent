import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Add the project root to the python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import types

# Mock google.cloud.storage
google = types.ModuleType("google")
google.cloud = types.ModuleType("google.cloud")
google.cloud.storage = MagicMock()
sys.modules["google"] = google
sys.modules["google.cloud"] = google.cloud
sys.modules["google.cloud.storage"] = google.cloud.storage

from MCP.uploader import GCSUploader

def verify_uploader():
    print("Verifying GCS Uploader logic with mocks...")
    
    os.environ["GCS_BUCKET_NAME"] = "test-bucket"
    
    with patch('google.cloud.storage.Client') as MockClient:
        mock_bucket = MockClient.return_value.bucket.return_value
        mock_blob = mock_bucket.blob.return_value
        
        uploader = GCSUploader()
        uri = uploader.upload_bytes(b"temp_data", content_type="image/jpeg")
        
        print(f"Returned URI: {uri}")
        
        if uri.startswith("gs://test-bucket/capture_"):
            print("[OK] URI format correct.")
        else:
            print("[FAIL] URI format incorrect.")
            
        mock_bucket.blob.assert_called()
        mock_blob.upload_from_string.assert_called_with(b"temp_data", content_type="image/jpeg")
        print("[OK] upload_from_string called.")

if __name__ == "__main__":
    verify_uploader()
