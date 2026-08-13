# Video Downloader Review Fixes Design

## Goal

Fix the confirmed edge cases without reducing the website coverage or changing the normal `auto` workflow.

## Decisions

- Keep `auto` behavior unchanged.
- Keep `strict` fallback to yt-dlp for compatibility, but print and document that the fallback is outside strict IP validation.
- Reject non-2xx responses before writing direct-download content.
- Treat total/low-speed `TimeoutError` as deterministic failures; continue retrying `httpx` transport errors.
- Match Douyin by parsed hostname and run desktop Chrome with its sandbox enabled.
- Add yt-dlp to Python dependencies and document FFmpeg/Deno as separately installed tools.
- Preserve `KeyboardInterrupt` after terminating the downloader process so the CLI reports cancellation.

## Testing

Add one regression test per behavior, run each test before implementation to verify it fails for the expected reason, then run the complete offline suite and focused behavior probes.

## Out of Scope

- Concurrent invocations sharing `.tmp`.
- Rare Windows reserved/trailing-dot video titles.
- System-level network sandboxing for yt-dlp.
