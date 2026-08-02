# Secure HTTP Direct-Link Downloader — Design Spec

**Date**: 2026-08-02
**Scope**: `extractors/http_downloader.py` (new module), `downloader.py` (integration)
**Status**: approved

---

## Motivation

`downloader._download_direct_url()` currently performs unbounded HTTP downloads of
CDN video URLs with no domain validation, private-IP filtering, size limits, or
atomic writes. This is the L4–L5 segment of a documented attack chain (URL
spoofing → SSRF → disk exhaustion → filename injection).

## Architecture

```
extractors/http_downloader.py   ← NEW: self-contained secure downloader
downloader.py                   ← MODIFIED: remove _download_direct_url, import new module
extractors/base.py              ← NOT modified this phase
```

`http_downloader` has zero dependency on the rest of the project. It is a
standalone module that takes a URL + safety constraints and returns a
`DownloadResult`.

## Public API

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DownloadConfig:
    max_size_bytes: int = 2 * 1024 * 1024 * 1024
    connect_timeout: float = 30.0
    read_timeout: float = 300.0
    total_timeout: float = 600.0
    min_speed_bytes_per_sec: int = 1024
    min_speed_window_sec: float = 30.0
    allowed_content_types: tuple[str, ...] = (
        "video/",
        "application/octet-stream",
    )
    max_redirects: int = 3
    overwrite: bool = False
    disk_safety_ratio: float = 1.2
    disk_check_interval_bytes: int = 64 * 1024 * 1024

@dataclass(frozen=True)
class DownloadResult:
    success: bool
    output_path: str
    bytes_downloaded: int
    error: str = ""

def download(
    url: str,
    output_dir: Path,
    filename: str,
    allowed_domains: list[str] | None = None,
    headers: dict[str, str] | None = None,
    config: DownloadConfig | None = None,
) -> DownloadResult:
```

## Security Requirements

### 1. Protocol — allow `http`, `https`; reject all others (`file`, `ftp`, `data`, `javascript`, …)

### 2. No userinfo in URL — reject `https://user:pass@host/path`

### 3. Domain allowlist — when `allowed_domains` is not None

- Lowercase, strip trailing `.`, IDNA-normalize
- Strict suffix match: `cdn.example.com` passes, `cdn.example.com.evil.com` rejected
- Re-checked on every redirect target

### 4. Private/special IP blocking

- Resolve hostname → all A/AAAA addresses before every connection
- Use `ipaddress.ip_address().is_global` + explicit checks for all reserved blocks
- IPv4: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 0.0.0.0/8, 224.0.0.0/4, 240.0.0.0/4
- IPv6: ::1, fc00::/7, fd00::/8, fe80::/10
- Mixed public+private → reject
- DNS failure → fail closed

### 5. DNS rebinding — custom `httpcore.NetworkBackend`

Override `connect_tcp()` to:
1. Resolve DNS via `socket.getaddrinfo()`
2. Validate all IPs
3. Connect socket to a validated IP
4. Return `NetworkStream` wrapping the connected socket

httpcore never does its own DNS resolution; no TOCTOU window.

Residual risk: hosts file subversion, unencrypted DNS on the wire.

### 6. No proxy — `trust_env=False`

No implicit HTTP_PROXY/HTTPS_PROXY inheritance. Explicit proxy config deferred
to a future phase with its own security model.

### 7. Redirect handling

- `follow_redirects=False`
- Iterative loop (not recursive), max `max_redirects` hops
- Re-validate protocol, domain, DNS/IP on every target
- Strip `Authorization`, `Cookie`, `Proxy-Authorization` on cross-origin redirect
- Detect redirect cycles

### 8. Content-Type validation

- Lowercase, strip parameters
- Allow `video/*`, `application/octet-stream`
- Reject text/html, application/json, text/plain, application/xml
- Missing Content-Type → reject

### 9. File size enforcement

- `Content-Length` > max → immediate reject
- Cumulative bytes > max → mid-stream abort
- Don't trust server-declared length alone

### 10. Timeouts

- Connect: 30s, Read: 300s, Total: 600s (wall-clock via `time.monotonic()`)
- Speed floor: sliding window of `min_speed_window_sec`, abort if < `min_speed_bytes_per_sec`
- 0-byte stall detection covered by read timeout

### 11. Filename safety (defense-in-depth)

Even though callers should sanitize, this module also:
- Rejects absolute paths, `..`, `/`, `\`, NUL, control chars
- Blocks Windows reserved names (CON, PRN, AUX, NUL, COM1–9, LPT1–9)
- Strips trailing spaces and dots
- Ensures resolved path is under `output_dir.resolve()`

### 12. No overwrite by default

- `overwrite=False` → auto-suffix: `video (1).mp4`, `video (2).mp4`, …
- `.part` files also use unique names

### 13. Disk space check

- `Content-Length` present: `free_space >= Content-Length * disk_safety_ratio`
- `Content-Length` absent: check before start, then every `disk_check_interval_bytes`
- Don't hard-require `max_size_bytes * safety_ratio` (would block legitimate dl)

### 14. Atomic write

```
{filename}.part → stream → flush → (fsync if needed) → os.replace → final
```

- Any failure → delete `.part`
- Final file never appears incomplete

### 15. Resource cleanup

- `with httpx.Client(...) as client:` — no leaked connections
- Response context manager
- `.part` cleanup in all exit paths

### 16. Output privacy

- Console: progress %, bytes, speed only
- No URLs, no CDN signatures, no headers in errors or stdout
- Error messages show sanitized domain at most

## Integration Plan

### `downloader.py` changes

1. Delete `_download_direct_url()` function
2. Import `download` from `extractors.http_downloader`
3. In `run_hybrid_download()`: call `download()` instead
4. Remove `video.url[:80]` printing
5. Distinguish all-success / partial-success / all-failure in output
6. Keep existing public functions (`build_command`, `run_download`, `check_environment`) unchanged

### `extractors/base.py`

Not modified. `VideoInfo.url` carries the CDN URL; the extractor's `allowed_domains`
parameter is passed by the caller via kwarg or extractor attribute. The existing
data structures are sufficient.

## Test Plan

New file: `tests/test_http_downloader.py`

30+ test cases using `httpx.MockTransport`, monkeypatch, temp dirs, fake DNS,
fake disk space, controlled time. No real network.

### Coverage matrix

| Category | Tests |
|----------|-------|
| Protocol | reject non-http/https, reject userinfo |
| DNS/IP | reject IPv4 private, IPv6 private, mixed, DNS failure |
| Domain allowlist | strict match, subdomain, reject lookalike |
| Redirect | re-check domain, re-check IP, relative URL, cycle, max hops, strip sensitive headers |
| Content-Type | reject HTML, JSON; accept video/*, octet-stream |
| Size | Content-Length exceeds max, cumulative bytes exceed max |
| Timeout | total timeout, slow download (sliding window) |
| Disk | space insufficient before start, space runs out mid-download |
| Filesystem | path traversal, Windows reserved names, no overwrite, auto-suffix, atomic rename |
| Resource | .part cleanup on failure, client closed, response closed |
| Privacy | no URLs in output |
| Integration | downloader.py hybrid flow with mock transport |

## Commit Sequence

1. `test: add security tests for direct HTTP downloads`
2. `feat: add SSRF-safe HTTP downloader module`
3. `refactor: integrate safe downloader into hybrid download flow`
4. `docs: document direct download security model and limitations`

## Non-Goals (this phase)

- Modifying `extractors/douyin.py` (URL matching, `--no-sandbox`, response filtering) — next phase
- Modifying `extractors/base.py`
- Proxy support
- Encrypted DNS (DoH/DoT)
- Browser profile security
