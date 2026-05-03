import logging
import shutil
import subprocess
import threading
import time
from glob import glob
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests import Response
from requests.adapters import HTTPAdapter
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

from automation.config import (
    ARIA2C_CONNECTION_CANDIDATES,
    ARIA2C_MAX_CONNECTIONS,
    ARIA2C_PATH,
    ARIA2C_TIMEOUT_SECONDS,
    DOWNLOAD_HARD_TIMEOUT_SECONDS,
    USE_ARIA2C,
    USER_AGENT,
)


CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 60
REQUEST_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
CHUNK_SIZE = 1024 * 1024
IDLE_TIMEOUT_SECONDS = 30
MAX_RETRIES = 4
BACKOFF_SECONDS = (1, 2, 4, 8)
MAX_RESOLVE_HOPS = 5
MAX_PARALLEL_PARTS = 8
MIN_PARALLEL_SIZE_BYTES = 4 * 1024 * 1024

logger = logging.getLogger("worker.downloader")


class DownloadError(Exception):
    pass


class DownloadStoppedError(DownloadError):
    pass


class DownloadTimeoutExceededError(DownloadError):
    pass


def _check_stop_requested(stop_requested: Callable[[], bool] | None) -> None:
    if stop_requested and stop_requested():
        raise DownloadStoppedError("Stopped by dashboard request during download")


def _build_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _filename_from_headers_or_url(response: Response, fallback: str) -> str:
    cd = response.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        filename = cd.split("filename=")[-1].strip().strip('"')
        if filename:
            return filename

    parsed = urlparse(response.url)
    name = Path(parsed.path).name
    return name or fallback


def _safe_output_path(target_dir: Path, filename: str) -> Path:
    file_path = target_dir / filename
    if not file_path.exists():
        return file_path

    try:
        file_path.unlink(missing_ok=True)
        return file_path
    except PermissionError:
        stem = file_path.stem
        suffix = file_path.suffix
        alt = target_dir / f"{stem}_{int(time.time())}{suffix}"
        logger.warning("Target file locked; using alternate file path: %s", alt)
        return alt


def _resolve_aria2c_bin() -> str | None:
    if ARIA2C_PATH != "aria2c":
        return ARIA2C_PATH

    bin_path = shutil.which("aria2c")
    if bin_path:
        return bin_path

    # WinGet install path fallback for shells that haven't reloaded PATH yet.
    local_app_data = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    pattern = str(local_app_data / "aria2.aria2_*" / "*" / "aria2c.exe")
    matches = sorted(glob(pattern), reverse=True)
    if matches:
        return matches[0]
    return None


def _compute_remaining_timeout_seconds(attempt_started_at: float) -> int:
    elapsed = time.monotonic() - attempt_started_at
    remaining = int(DOWNLOAD_HARD_TIMEOUT_SECONDS - elapsed)
    if remaining <= 0:
        raise DownloadTimeoutExceededError(
            f"Download exceeded hard timeout of {DOWNLOAD_HARD_TIMEOUT_SECONDS} seconds"
        )
    return remaining


def _download_with_aria2c(
    final_url: str,
    headers: dict,
    file_path: Path,
    attempt_started_at: float,
    cookie_header: str | None = None,
) -> bool:
    if not USE_ARIA2C:
        return False

    aria2c_bin = _resolve_aria2c_bin()
    if not aria2c_bin:
        logger.info("aria2c not found on PATH; falling back to Python downloader")
        return False

    connection_candidates = sorted(
        {max(1, value) for value in ARIA2C_CONNECTION_CANDIDATES if isinstance(value, int)},
        reverse=True,
    ) or [max(1, ARIA2C_MAX_CONNECTIONS)]

    base_args = [
        aria2c_bin,
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--continue=true",
        "--file-allocation=none",
        "--disable-ipv6=true",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--max-tries=3",
        "--retry-wait=2",
        f"--connect-timeout={CONNECT_TIMEOUT_SECONDS}",
        f"--timeout={READ_TIMEOUT_SECONDS}",
        "--min-split-size=1M",
        f"--user-agent={USER_AGENT}",
        f"--dir={str(file_path.parent)}",
        f"--out={file_path.name}",
    ]

    referer = headers.get("Referer")
    if referer:
        base_args.append(f"--referer={referer}")
    if cookie_header:
        base_args.append(f"--header=Cookie: {cookie_header}")

    for conn in connection_candidates:
        args = list(base_args)
        args.extend([f"--max-connection-per-server={conn}", f"--split={conn}", final_url])
        timeout = min(ARIA2C_TIMEOUT_SECONDS, _compute_remaining_timeout_seconds(attempt_started_at))
        logger.info("Trying aria2c download | file=%s | conns=%s | timeout=%ss", file_path.name, conn, timeout)
        try:
            subprocess.run(
                args,
                check=True,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.TimeoutExpired:
            logger.warning("aria2c timed out (conns=%s, timeout=%ss); trying fallback path", conn, timeout)
            continue
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            reason = stderr[:300] if stderr else stdout[:300]
            logger.warning("aria2c failed (conns=%s, rc=%s): %s", conn, exc.returncode, reason)
            continue
        except DownloadTimeoutExceededError:
            raise
        except Exception as exc:
            logger.warning("aria2c unexpected error (conns=%s): %s", conn, exc)
            continue

        if not file_path.exists() or file_path.stat().st_size <= 0:
            logger.warning("aria2c completed but file missing/empty (conns=%s)", conn)
            continue

        logger.info("aria2c download success | conns=%s | file=%s | bytes=%s", conn, file_path, file_path.stat().st_size)
        return True

    logger.warning("aria2c did not complete successfully for any connection candidate; fallback to Python downloader")
    return False


def _is_probable_binary_response(response: Response) -> bool:
    content_type = response.headers.get("Content-Type", "").lower()
    binary_types = (
        "application/vnd.android.package-archive",
        "application/octet-stream",
        "application/zip",
        "application/x-zip",
        "application/x-zip-compressed",
        "application/java-archive",
        "binary",
    )
    return any(t in content_type for t in binary_types)


def _extract_download_link_from_html(page_url: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    candidates = []
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href:
            continue

        text = link.get_text(" ", strip=True).lower()
        title = link.get("title", "").lower()
        joined = f"{href.lower()} {text} {title}"

        score = 0
        if "download" in joined:
            score += 5
        if any(ext in joined for ext in [".apk", ".xapk", ".apks", ".zip"]):
            score += 10
        if "/download" in href.lower():
            score += 3

        if score > 0:
            candidates.append((score, urljoin(page_url, href)))

    if not candidates:
        raise DownloadError("No download link found on detail page")

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _resolve_final_download_url(download_url: str, session: requests.Session, base_headers: dict) -> tuple[str, str | None]:
    current_url = download_url
    referer = None

    for _ in range(MAX_RESOLVE_HOPS):
        headers = dict(base_headers)
        if referer:
            headers["Referer"] = referer

        with session.get(
            current_url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        ) as response:
            response.raise_for_status()

            if _is_probable_binary_response(response):
                return response.url, referer

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type or "application/xhtml" in content_type:
                next_url = _extract_download_link_from_html(response.url, response.text)
                referer = response.url
                current_url = next_url
                continue

            return response.url, referer

    raise DownloadError("Could not resolve final binary download URL within max hops")


def _probe_download(session: requests.Session, final_url: str, headers: dict) -> tuple[int | None, str]:
    with session.get(
        final_url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        stream=True,
        allow_redirects=True,
    ) as response:
        response.raise_for_status()
        if not _is_probable_binary_response(response):
            raise DownloadError(
                "Resolved URL did not return binary content "
                f"(type={response.headers.get('Content-Type', '')})"
            )

        content_length = response.headers.get("Content-Length")
        size = int(content_length) if content_length and content_length.isdigit() else None
        filename = _filename_from_headers_or_url(response, "download.bin")
        return size, filename


def _supports_http_range(session: requests.Session, final_url: str, headers: dict) -> bool:
    probe_headers = dict(headers)
    probe_headers["Range"] = "bytes=0-0"
    with session.get(
        final_url,
        headers=probe_headers,
        timeout=REQUEST_TIMEOUT,
        stream=True,
        allow_redirects=True,
    ) as response:
        if response.status_code != 206:
            return False
        content_range = response.headers.get("Content-Range", "")
        return content_range.startswith("bytes 0-0/")


def _download_range_part(
    final_url: str,
    headers: dict,
    start: int,
    end: int,
    part_path: Path,
    errors: list,
    idx: int,
    stop_requested: Callable[[], bool] | None = None,
) -> None:
    part_headers = dict(headers)
    part_headers["Range"] = f"bytes={start}-{end}"

    try:
        _check_stop_requested(stop_requested)
        with requests.get(
            final_url,
            headers=part_headers,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:
            if response.status_code != 206:
                raise DownloadError(f"Range request failed with status {response.status_code}")

            bytes_received = 0
            last_data_at = time.monotonic()

            with open(part_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    _check_stop_requested(stop_requested)
                    now = time.monotonic()
                    if chunk:
                        file.write(chunk)
                        bytes_received += len(chunk)
                        last_data_at = now
                    elif now - last_data_at > IDLE_TIMEOUT_SECONDS:
                        raise DownloadError(f"Part {idx}: stalled for {IDLE_TIMEOUT_SECONDS}s")

                    if now - last_data_at > IDLE_TIMEOUT_SECONDS:
                        raise DownloadError(f"Part {idx}: stalled for {IDLE_TIMEOUT_SECONDS}s")

            if bytes_received <= 0:
                raise DownloadError(f"Part {idx}: downloaded 0 bytes")
    except Exception as exc:
        errors.append(exc)


def _download_parallel(
    final_url: str,
    headers: dict,
    file_path: Path,
    total_size: int,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    part_size = total_size // MAX_PARALLEL_PARTS
    ranges = []
    start = 0
    for idx in range(MAX_PARALLEL_PARTS):
        end = (start + part_size - 1) if idx < MAX_PARALLEL_PARTS - 1 else total_size - 1
        ranges.append((idx, start, end))
        start = end + 1

    part_paths = [file_path.with_suffix(f".part{idx}") for idx, _, _ in ranges]
    errors: list[Exception] = []
    threads = []

    for (idx, rstart, rend), part_path in zip(ranges, part_paths):
        thread = threading.Thread(
            target=_download_range_part,
            args=(final_url, headers, rstart, rend, part_path, errors, idx, stop_requested),
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    if errors:
        for part in part_paths:
            part.unlink(missing_ok=True)
        raise DownloadError(f"Parallel download failed: {errors[0]}")

    merged_bytes = 0
    with open(file_path, "wb") as out_file:
        for part in part_paths:
            with open(part, "rb") as pf:
                while True:
                    chunk = pf.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    merged_bytes += len(chunk)
            part.unlink(missing_ok=True)

    if merged_bytes != total_size:
        raise DownloadError(f"Parallel merge size mismatch: got={merged_bytes}, expected={total_size}")

    return merged_bytes


def _download_single_resumable(
    session: requests.Session,
    final_url: str,
    headers: dict,
    file_path: Path,
    total_size: int | None,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    bytes_received = 0
    file_path.unlink(missing_ok=True)

    while True:
        _check_stop_requested(stop_requested)
        part_headers = dict(headers)
        if bytes_received > 0:
            part_headers["Range"] = f"bytes={bytes_received}-"

        with session.get(
            final_url,
            headers=part_headers,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:
            if response.status_code not in (200, 206):
                raise DownloadError(f"Unexpected status during stream: {response.status_code}")
            if not _is_probable_binary_response(response):
                raise DownloadError(
                    f"Stream did not return binary content (type={response.headers.get('Content-Type', '')})"
                )

            mode = "ab" if bytes_received > 0 else "wb"
            last_data_at = time.monotonic()
            with open(file_path, mode) as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    _check_stop_requested(stop_requested)
                    now = time.monotonic()
                    if chunk:
                        file.write(chunk)
                        bytes_received += len(chunk)
                        last_data_at = now
                    elif now - last_data_at > IDLE_TIMEOUT_SECONDS:
                        raise DownloadError(f"No bytes received for {IDLE_TIMEOUT_SECONDS} seconds")

                    if now - last_data_at > IDLE_TIMEOUT_SECONDS:
                        raise DownloadError(f"No bytes received for {IDLE_TIMEOUT_SECONDS} seconds")

        if total_size is None:
            return bytes_received
        if bytes_received >= total_size:
            return bytes_received

        logger.warning("Resuming download from offset=%s/%s", bytes_received, total_size)


def download_file(
    download_url: str,
    target_dir: Path,
    fallback_name: str,
    stop_requested: Callable[[], bool] | None = None,
) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)

    base_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    total_attempts = MAX_RETRIES + 1
    last_error: Exception | None = None
    hard_timeout_started_at = time.monotonic()

    for attempt in range(1, total_attempts + 1):
        if (time.monotonic() - hard_timeout_started_at) >= DOWNLOAD_HARD_TIMEOUT_SECONDS:
            raise DownloadTimeoutExceededError(
                f"Download exceeded hard timeout of {DOWNLOAD_HARD_TIMEOUT_SECONDS} seconds"
            )
        logger.info("Download start | attempt=%s/%s | url=%s", attempt, total_attempts, download_url)
        attempt_start = time.monotonic()

        try:
            _check_stop_requested(stop_requested)

            def _combined_stop_requested() -> bool:
                if stop_requested and stop_requested():
                    return True
                return (time.monotonic() - hard_timeout_started_at) >= DOWNLOAD_HARD_TIMEOUT_SECONDS

            with _build_session() as session:
                final_url, referer = _resolve_final_download_url(download_url, session, base_headers)

                headers = dict(base_headers)
                if referer:
                    headers["Referer"] = referer

                size, detected_filename = _probe_download(session, final_url, headers)

                filename = detected_filename
                if not filename.lower().endswith((".apk", ".xapk", ".apks", ".zip", ".bin")):
                    filename = fallback_name

                file_path = _safe_output_path(target_dir, filename)
                cookie_map = session.cookies.get_dict(domain=urlparse(final_url).hostname or "")
                if not cookie_map:
                    cookie_map = session.cookies.get_dict()
                cookie_header = "; ".join(f"{key}={value}" for key, value in cookie_map.items()) if cookie_map else None

                if _download_with_aria2c(
                    final_url,
                    headers,
                    file_path,
                    hard_timeout_started_at,
                    cookie_header=cookie_header,
                ):
                    return file_path

                use_parallel = bool(size and size >= MIN_PARALLEL_SIZE_BYTES) and _supports_http_range(
                    session, final_url, headers
                )

                if use_parallel:
                    logger.info("Using parallel Python download | parts=%s | size=%s", MAX_PARALLEL_PARTS, size)
                    bytes_total = _download_parallel(
                        final_url,
                        headers,
                        file_path,
                        int(size),
                        stop_requested=_combined_stop_requested,
                    )
                else:
                    logger.info("Using resumable single-stream Python download | size=%s", size)
                    bytes_total = _download_single_resumable(
                        session,
                        final_url,
                        headers,
                        file_path,
                        size,
                        stop_requested=_combined_stop_requested,
                    )

                logger.info(
                    "Download success | attempt=%s/%s | file=%s | bytes=%s | elapsed=%.2fs",
                    attempt,
                    total_attempts,
                    file_path,
                    bytes_total,
                    time.monotonic() - attempt_start,
                )
                return file_path

        except DownloadStoppedError:
            if (time.monotonic() - hard_timeout_started_at) >= DOWNLOAD_HARD_TIMEOUT_SECONDS:
                raise DownloadTimeoutExceededError(
                    f"Download exceeded hard timeout of {DOWNLOAD_HARD_TIMEOUT_SECONDS} seconds"
                )
            raise
        except DownloadTimeoutExceededError:
            raise
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (403, 404, 410):
                # Fatal errors, do not retry
                error_message = f"{exc.response.status_code} Client Error: {exc.response.reason} for url: {exc.response.url}"
                logger.error("Download fatal HTTP error | url=%s | error=%s", download_url, error_message)
                raise DownloadError(error_message)
            last_error = exc
            logger.error("Download HTTP error | attempt=%s/%s | error=%s", attempt, total_attempts, exc)
        except Timeout as exc:
            last_error = exc
            logger.error("Download timeout | attempt=%s/%s | error=%s", attempt, total_attempts, exc)
        except ConnectionError as exc:
            last_error = exc
            logger.error("Download connection error | attempt=%s/%s | error=%s", attempt, total_attempts, exc)
        except ChunkedEncodingError as exc:
            last_error = exc
            logger.error("Download chunked encoding error | attempt=%s/%s | error=%s", attempt, total_attempts, exc)
        except Exception as exc:
            last_error = exc
            logger.error("Download unexpected error | attempt=%s/%s | error=%s", attempt, total_attempts, exc)

        if attempt <= MAX_RETRIES:
            backoff = BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]
            logger.warning(
                "Retrying download | next_attempt=%s/%s | backoff_seconds=%s | url=%s",
                attempt + 1,
                total_attempts,
                backoff,
                download_url,
            )
            for _ in range(backoff):
                _check_stop_requested(stop_requested)
                time.sleep(1)

    error_message = f"Download failed after {total_attempts} attempts: {last_error}"
    logger.error("Download final failure | url=%s | error=%s", download_url, error_message)
    raise DownloadError(error_message)


