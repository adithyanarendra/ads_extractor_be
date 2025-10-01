import boto3
from app.config import (
    R2_BUCKET,
    R2_ENDPOINT,
    R2_ACCESS_KEY,
    R2_SECRET_KEY,
    ACCOUNT_HASH,
)

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
)


def upload_to_r2(file_obj, filename: str) -> str:
    """
    Upload file object to R2 and return the public URL
    """
    s3.upload_fileobj(file_obj, R2_BUCKET, filename, ExtraArgs={"ACL": "public-read"})
    return f"https://pub-{ACCOUNT_HASH}.r2.dev/{filename}"


def get_file_from_r2(filename: str):
    """
    Fetch file object from R2 for streaming
    """
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=filename)
        return obj["Body"]
    except Exception as e:
        print(f"Error fetching file {filename} from R2: {e}")
        return None
