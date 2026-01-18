import os
import datetime
from google.cloud import storage
import uuid

class GCSUploader:
    def __init__(self, bucket_name: str = None):
        self.bucket_name = bucket_name or os.environ.get("GCS_BUCKET_NAME")
        if not self.bucket_name:
            raise ValueError("GCS_BUCKET_NAME must be set in environment variables.")
        
        self.client = storage.Client()
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_bytes(self, data: bytes, content_type: str = "image/jpeg") -> str:
        """Uploads bytes to GCS and returns the gs:// URI."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        extension = content_type.split("/")[-1]
        filename = f"capture_{timestamp}_{unique_id}.{extension}"
        
        blob = self.bucket.blob(filename)
        blob.upload_from_string(data, content_type=content_type)
        
        return f"gs://{self.bucket_name}/{filename}"
