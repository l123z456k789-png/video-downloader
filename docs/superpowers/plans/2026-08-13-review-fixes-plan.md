# Video Downloader Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct confirmed download edge cases while preserving current site compatibility.

**Architecture:** Make surgical checks at the existing boundaries: HTTP response validation, retry classification, extractor URL routing, subprocess cancellation, and installation metadata. Keep the current hybrid downloader and fallback chain.

**Tech Stack:** Python 3.12, pytest, httpx/httpcore, Playwright, yt-dlp.

## Global Constraints

- `auto` behavior and website coverage remain unchanged.
- `strict` retains yt-dlp fallback and warns when leaving strict IP validation.
- Every production behavior change follows a red-green regression test.
- Personal configuration, cookies, logs, profiles, and downloaded videos are untouched.

---

### Task 1: HTTP status and timeout handling

**Files:**
- Modify: `extractors/http_downloader.py`
- Test: `tests/test_http_downloader.py`

- [ ] Add a test proving a 404 octet-stream response is rejected and no output is created.
- [ ] Run the focused test and verify it fails because the response is currently saved.
- [ ] Add a test proving total timeout is not retried.
- [ ] Run it and verify the current attempt count is greater than one.
- [ ] Add the minimal status check and retry-classification fix.
- [ ] Run focused tests and verify they pass.

### Task 2: Douyin routing and browser sandbox

**Files:**
- Modify: `extractors/douyin.py`
- Test: `tests/test_extractors.py`

- [ ] Add tests for exact/subdomain acceptance and query-string/lookalike rejection.
- [ ] Add a focused test for the persistent-context launch arguments.
- [ ] Run focused tests and verify the false-positive and no-sandbox expectations fail.
- [ ] Parse the hostname and remove `--no-sandbox`.
- [ ] Run focused tests and verify they pass.

### Task 3: Fallback disclosure and cancellation

**Files:**
- Modify: `downloader.py`
- Test: `tests/test_downloader.py`

- [ ] Add a test proving strict fallback prints the IP-validation warning.
- [ ] Add a test proving `_run_process` terminates its child and re-raises `KeyboardInterrupt`.
- [ ] Run both tests and verify they fail for the current behavior.
- [ ] Add the warning at strict fallback boundaries and preserve `KeyboardInterrupt`.
- [ ] Run focused tests and verify they pass.

### Task 4: Installation metadata and documentation

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] Add `yt-dlp` to Python dependencies.
- [ ] Correct first-install and strict-mode documentation for FFmpeg, Deno, and fallback protection.

### Task 5: Verification and commit

**Files:**
- Verify all modified files.

- [ ] Run the complete offline pytest suite with a writable base temp directory.
- [ ] Run focused probes for 404 rejection, timeout attempt count, and Douyin false positives.
- [ ] Review `git diff --check`, `git diff`, and repository status.
- [ ] Commit the verified fixes without pushing unless explicitly requested.
