"""
Google Cloud Storage (GCS) Uploader Utility.

Provides a simple interface for uploading byte data to Google Cloud Storage
and returning gs:// URIs for use with Gemini models.

Environment Variables:
- GCS_BUCKET_NAME: The GCS bucket name (required)
- GOOGLE_APPLICATION_CREDENTIALS: Path to service account key (required)

Usage:
    from MCP.uploader import GCSUploader
    
    uploader = GCSUploader()
    uri = uploader.upload_bytes(image_bytes, content_type="image/jpeg", folder="captures")
    # Returns: gs://bucket-name/captures/capture_20260118_144800_abc123.jpeg
"""

import os
import datetime
from google.cloud import storage
import uuid

class GCSUploader:
    """
    Handles uploading binary data to Google Cloud Storage.
    
    Attributes:
        bucket_name (str): The GCS bucket name
        client: Google Cloud Storage client
        bucket: GCS bucket object
    """
    def __init__(self, bucket_name: str = None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME")
        if not self.bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set in environment variables.")
        
        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_bytes(self, data: bytes, content_type: str = "image/jpeg", folder: str = "") -> str:
        """
        Uploads bytes to GCS and returns the gs:// URI.
        
        Args:
            data: Binary data to upload
            content_type: MIME type (default: "image/jpeg")
            folder: Optional folder prefix (default: "")
            
        Returns:
            str: GCS URI in format gs://bucket-name/path/to/file
            
        Example:
            uri = uploader.upload_bytes(image_bytes, content_type="image/jpeg", folder="agent-captures")
            # Returns: gs://my-bucket/agent-captures/capture_20260118_144800_abc123.jpeg
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        extension = content_type.split("/")[-1]
        
        filename = f"capture_{timestamp}_{unique_id}.{extension}"
        if folder:
            filename = f"{folder.rstrip('/')}/{filename}"
        
        blob = self.bucket.blob(filename)
        blob.upload_from_string(data, content_type=content_type)
        
        return f"gs://{self.bucket_name}/{filename}"
