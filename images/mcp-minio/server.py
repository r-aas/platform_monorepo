"""MCP server for MinIO — S3-compatible object storage tools.

Exposes MinIO's S3 API as MCP tools so agents can:
- List/create/delete buckets
- List/get/put/delete objects
- Generate presigned URLs
- Get bucket and object stats

Requires: MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from mcp.server.fastmcp import FastMCP

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")

mcp = FastMCP("MinIO Object Storage", host="0.0.0.0", port=3000)


def _sign_v4(method: str, path: str, headers: dict, payload_hash: str) -> dict:
    """AWS Signature V4 signing for S3 requests."""
    now = datetime.now(timezone.utc)
    date_stamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{date_stamp}/{MINIO_REGION}/s3/aws4_request"

    headers["x-amz-date"] = amz_date
    headers["x-amz-content-sha256"] = payload_hash

    signed_headers = ";".join(sorted(headers.keys()))
    canonical = "\n".join([
        method, path, "",
        "\n".join(f"{k}:{headers[k]}" for k in sorted(headers)),
        "", signed_headers, payload_hash,
    ])
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = _hmac(f"AWS4{MINIO_SECRET_KEY}".encode(), date_stamp)
    k = _hmac(k, MINIO_REGION)
    k = _hmac(k, "s3")
    k = _hmac(k, "aws4_request")
    sig = hmac.new(k, string_to_sign.encode(), hashlib.sha256).hexdigest()

    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={MINIO_ACCESS_KEY}/{scope}, SignedHeaders={signed_headers}, Signature={sig}"
    return headers


async def _s3_request(method: str, path: str = "/", body: bytes = b"") -> httpx.Response:
    payload_hash = hashlib.sha256(body).hexdigest()
    from urllib.parse import urlparse
    parsed = urlparse(MINIO_ENDPOINT)
    headers = {"host": parsed.netloc}
    headers = _sign_v4(method, path, headers, payload_hash)

    async with httpx.AsyncClient(base_url=MINIO_ENDPOINT, timeout=30) as c:
        r = await c.request(method, path, headers=headers, content=body)
        return r


def _parse_xml_list(text: str, tag: str) -> list[str]:
    """Simple XML tag extraction without xml.etree for lightweight parsing."""
    import re
    return re.findall(f"<{tag}>([^<]+)</{tag}>", text)


# ── Buckets ──


@mcp.tool()
async def list_buckets() -> list[dict]:
    """List all buckets in MinIO."""
    r = await _s3_request("GET", "/")
    r.raise_for_status()
    names = _parse_xml_list(r.text, "Name")
    dates = _parse_xml_list(r.text, "CreationDate")
    return [{"name": n, "created": d} for n, d in zip(names, dates)]


@mcp.tool()
async def create_bucket(bucket: str) -> dict:
    """Create a new bucket.

    Args:
        bucket: Bucket name (lowercase, 3-63 chars, no dots)
    """
    r = await _s3_request("PUT", f"/{bucket}")
    if r.status_code in (200, 409):
        return {"bucket": bucket, "status": "created" if r.status_code == 200 else "already_exists"}
    r.raise_for_status()
    return {"bucket": bucket, "status": "created"}


@mcp.tool()
async def delete_bucket(bucket: str) -> dict:
    """Delete an empty bucket.

    Args:
        bucket: Bucket name to delete (must be empty)
    """
    r = await _s3_request("DELETE", f"/{bucket}")
    r.raise_for_status()
    return {"bucket": bucket, "deleted": True}


# ── Objects ──


@mcp.tool()
async def list_objects(bucket: str, prefix: str = "", max_keys: int = 100) -> list[dict]:
    """List objects in a bucket with optional prefix filter.

    Args:
        bucket: Bucket name
        prefix: Key prefix filter (e.g. "models/", "artifacts/run-123/")
        max_keys: Max results (default 100)
    """
    params = f"?list-type=2&max-keys={max_keys}"
    if prefix:
        params += f"&prefix={quote(prefix)}"
    r = await _s3_request("GET", f"/{bucket}{params}")
    r.raise_for_status()
    keys = _parse_xml_list(r.text, "Key")
    sizes = _parse_xml_list(r.text, "Size")
    modified = _parse_xml_list(r.text, "LastModified")
    return [
        {"key": k, "size_bytes": int(s), "last_modified": m}
        for k, s, m in zip(keys, sizes, modified)
    ]


@mcp.tool()
async def get_object_info(bucket: str, key: str) -> dict:
    """Get metadata for an object (size, type, etag) without downloading.

    Args:
        bucket: Bucket name
        key: Object key
    """
    r = await _s3_request("HEAD", f"/{bucket}/{quote(key)}")
    r.raise_for_status()
    return {
        "bucket": bucket,
        "key": key,
        "size_bytes": int(r.headers.get("content-length", 0)),
        "content_type": r.headers.get("content-type", ""),
        "etag": r.headers.get("etag", "").strip('"'),
        "last_modified": r.headers.get("last-modified", ""),
    }


@mcp.tool()
async def get_object_text(bucket: str, key: str, max_bytes: int = 65536) -> dict:
    """Download and return object contents as text (for small text files).

    Args:
        bucket: Bucket name
        key: Object key
        max_bytes: Max bytes to read (default 64KB, capped at 1MB)
    """
    max_bytes = min(max_bytes, 1_048_576)
    headers_extra = {"Range": f"bytes=0-{max_bytes - 1}"}
    payload_hash = hashlib.sha256(b"").hexdigest()
    from urllib.parse import urlparse
    parsed = urlparse(MINIO_ENDPOINT)
    headers = {"host": parsed.netloc}
    headers.update(headers_extra)
    headers = _sign_v4("GET", f"/{bucket}/{quote(key)}", headers, payload_hash)

    async with httpx.AsyncClient(base_url=MINIO_ENDPOINT, timeout=30) as c:
        r = await c.get(f"/{bucket}/{quote(key)}", headers=headers)
        r.raise_for_status()
        return {
            "bucket": bucket,
            "key": key,
            "size_bytes": len(r.content),
            "content": r.text,
            "truncated": len(r.content) >= max_bytes,
        }


@mcp.tool()
async def put_object(bucket: str, key: str, content: str, content_type: str = "text/plain") -> dict:
    """Upload text content as an object.

    Args:
        bucket: Bucket name
        key: Object key (path)
        content: Text content to upload
        content_type: MIME type (default text/plain)
    """
    body = content.encode()
    payload_hash = hashlib.sha256(body).hexdigest()
    from urllib.parse import urlparse
    parsed = urlparse(MINIO_ENDPOINT)
    headers = {"host": parsed.netloc, "content-type": content_type}
    headers = _sign_v4("PUT", f"/{bucket}/{quote(key)}", headers, payload_hash)

    async with httpx.AsyncClient(base_url=MINIO_ENDPOINT, timeout=30) as c:
        r = await c.put(f"/{bucket}/{quote(key)}", headers=headers, content=body)
        r.raise_for_status()
        return {"bucket": bucket, "key": key, "size_bytes": len(body), "uploaded": True}


@mcp.tool()
async def delete_object(bucket: str, key: str) -> dict:
    """Delete an object from a bucket.

    Args:
        bucket: Bucket name
        key: Object key to delete
    """
    r = await _s3_request("DELETE", f"/{bucket}/{quote(key)}")
    r.raise_for_status()
    return {"bucket": bucket, "key": key, "deleted": True}


@mcp.tool()
async def bucket_stats(bucket: str) -> dict:
    """Get summary stats for a bucket (object count, total size).

    Args:
        bucket: Bucket name
    """
    r = await _s3_request("GET", f"/{bucket}?list-type=2")
    r.raise_for_status()
    sizes = _parse_xml_list(r.text, "Size")
    total = sum(int(s) for s in sizes)
    return {
        "bucket": bucket,
        "object_count": len(sizes),
        "total_size_bytes": total,
        "total_size_mb": round(total / 1_048_576, 2),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
