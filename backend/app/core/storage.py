import asyncio
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from urllib.parse import quote, unquote, urlparse

try:
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - dependencies are installed in runtime images
    Config = None  # type: ignore[assignment,misc]

    class BotoCoreError(Exception):
        pass

    class ClientError(Exception):
        pass

from app.core.config import get_settings


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class SignedUrls:
    """Outcome of one batch signing pass.

    ``urls`` maps each signed key to its URL, ``failed`` lists the keys that
    were not signed (invalid keys included, in input order) and ``reason`` is
    ``"build_failed"``, ``"sign_failed"`` or ``None`` when everything worked.
    """

    urls: dict[str, str]
    failed: tuple[str, ...] = ()
    reason: str | None = None


def _is_valid_key(key: object) -> bool:
    if not isinstance(key, str) or not key or key.startswith("/"):
        return False
    return ".." not in key.split("/")


class ObjectStorage:
    """Small S3-compatible adapter used for player media."""

    def __init__(self, client_factory: Callable[[str | None], object] | None = None):
        self.settings = get_settings()
        self._bucket_ready = False
        self._bucket_lock = Lock()
        self._clients: dict[str, object] = {}
        self._clients_lock = Lock()
        self._client_factory = client_factory

    def _client(self, endpoint_url: str | None = None):
        """Build an upload/delete client; that path keeps one client per call."""

        return self._build_client(endpoint_url)

    def _build_client(self, endpoint_url: str | None = None):
        if self.settings.storage_provider not in {"s3", "gcs"}:
            raise StorageError("Proveedor de almacenamiento no soportado")
        import boto3

        client_kwargs = {
            "endpoint_url": endpoint_url or self.settings.storage_endpoint_url,
            "region_name": self.settings.storage_region,
            "aws_access_key_id": self.settings.storage_access_key,
            "aws_secret_access_key": self.settings.storage_secret_key,
        }
        if Config is not None and client_kwargs["endpoint_url"]:
            client_kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )
        return boto3.client("s3", **client_kwargs)

    def _get_or_build_client(self, endpoint_url: str | None):
        """Return the process-wide signing client for an effective endpoint.

        The double-checked lock guarantees exactly one construction per endpoint
        even when two cold requests race. A failed construction leaves the cache
        untouched, so the next request retries.
        """

        cache_key = endpoint_url or ""
        client = self._clients.get(cache_key)
        if client is not None:
            return client
        with self._clients_lock:
            client = self._clients.get(cache_key)
            if client is None:
                factory = self._client_factory or self._build_client
                client = factory(endpoint_url)
                self._clients[cache_key] = client
            return client

    def _ensure_bucket(self, client) -> None:
        with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                client.head_bucket(Bucket=self.settings.storage_bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                create_kwargs = {"Bucket": self.settings.storage_bucket}
                if self.settings.storage_region != "us-east-1":
                    create_kwargs["CreateBucketConfiguration"] = {
                        "LocationConstraint": self.settings.storage_region,
                    }
                client.create_bucket(**create_kwargs)
            # Harden an existing local bucket once per process, not once per upload.
            if self.settings.storage_endpoint_url:
                try:
                    client.delete_bucket_policy(Bucket=self.settings.storage_bucket)
                except ClientError as exc:
                    code = str(exc.response.get("Error", {}).get("Code", ""))
                    if code not in {"404", "NoSuchBucketPolicy", "NoSuchBucket", "NotFound"}:
                        raise
            self._bucket_ready = True

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        if len(content) > self.settings.storage_max_image_bytes:
            raise StorageError("La imagen supera el tamaño máximo permitido")
        try:
            client = self._client()
            await asyncio.to_thread(self._ensure_bucket, client)
            await asyncio.to_thread(
                client.put_object,
                Bucket=self.settings.storage_bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                CacheControl="private, max-age=300",
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("No se pudo guardar el objeto") from exc
        return key

    async def delete_key(self, key: str) -> None:
        try:
            client = self._client()
            await asyncio.to_thread(
                client.delete_object,
                Bucket=self.settings.storage_bucket,
                Key=key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("No se pudo eliminar el objeto") from exc

    def _signing_endpoint_url(self) -> str | None:
        if self.settings.storage_signing_endpoint_url:
            return self.settings.storage_signing_endpoint_url
        if self.settings.storage_public_base_url:
            parsed = urlparse(self.settings.storage_public_base_url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        return self.settings.storage_endpoint_url

    def _sign_many(
        self,
        endpoint_url: str | None,
        keys: Sequence[str],
        ttl: int,
    ) -> SignedUrls:
        """Sign every key synchronously; always runs off the event loop."""

        try:
            client = self._get_or_build_client(endpoint_url)
        except Exception:
            return SignedUrls(urls={}, failed=tuple(keys), reason="build_failed")

        urls: dict[str, str] = {}
        failed: list[str] = []
        for key in keys:
            try:
                urls[key] = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.settings.storage_bucket, "Key": key},
                    ExpiresIn=ttl,
                )
            except Exception:
                failed.append(key)
        return SignedUrls(
            urls=urls,
            failed=tuple(failed),
            reason="sign_failed" if failed else None,
        )

    async def signed_urls(
        self,
        keys: Iterable[str],
        expires_seconds: int | None = None,
    ) -> SignedUrls:
        """Resolve a whole batch with one off-thread dispatch and one client.

        Keys are deduplicated, invalid keys are reported in ``failed`` without
        reaching the client, and one failing key never blocks the others.
        """

        ordered = list(dict.fromkeys(keys))
        if not ordered:
            return SignedUrls(urls={})

        ttl = expires_seconds or self.settings.storage_presign_seconds
        valid_keys = tuple(key for key in ordered if _is_valid_key(key))
        invalid_keys = tuple(key for key in ordered if not _is_valid_key(key))

        signed = SignedUrls(urls={})
        if valid_keys:
            signed = await asyncio.to_thread(
                self._sign_many,
                self._signing_endpoint_url(),
                valid_keys,
                ttl,
            )

        reason = signed.reason
        if reason is None and invalid_keys:
            reason = "sign_failed"
        return SignedUrls(
            urls=dict(signed.urls),
            failed=tuple(key for key in ordered if key not in signed.urls),
            reason=reason,
        )

    async def signed_url(self, key: str, expires_seconds: int | None = None) -> str:
        if not _is_valid_key(key):
            raise StorageError("La clave del objeto no es válida")
        result = await self.signed_urls([key], expires_seconds)
        url = result.urls.get(key)
        if not url:
            raise StorageError("No se pudo generar el enlace de la foto")
        return url

    def public_url(self, key: str) -> str:
        encoded_key = quote(key, safe="/")
        if self.settings.storage_public_base_url:
            return f"{self.settings.storage_public_base_url.rstrip('/')}/{encoded_key}"
        if self.settings.storage_endpoint_url:
            return f"{self.settings.storage_endpoint_url.rstrip('/')}/{self.settings.storage_bucket}/{encoded_key}"
        return f"https://{self.settings.storage_bucket}.s3.{self.settings.storage_region}.amazonaws.com/{encoded_key}"

    def key_from_url(self, value: str | None) -> str | None:
        if not value:
            return None
        base = self.settings.storage_public_base_url
        if base and value.startswith(f"{base.rstrip('/')}/"):
            return unquote(value[len(base.rstrip("/")) + 1:])
        if self.settings.storage_endpoint_url:
            prefix = f"{self.settings.storage_endpoint_url.rstrip('/')}/{self.settings.storage_bucket}/"
            if value.startswith(prefix):
                return unquote(value[len(prefix):])
        parsed = urlparse(value)
        suffix = f"/{self.settings.storage_bucket}/"
        if suffix in parsed.path:
            return unquote(parsed.path.split(suffix, 1)[1])
        return None


@lru_cache
def get_object_storage() -> ObjectStorage:
    return ObjectStorage()
