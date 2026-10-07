# Public release checklist

1. Replace `canonical_source` in `公开发布信息.json` with the actual GitHub URL.
2. Copy `LICENSE-TRANSLATION.txt`, `monitor_phrases.txt`, `monitor_public_reuse.py`, and `.github/workflows/monitor-reuse.yml` into the repository.
3. Keep the game zip in a GitHub Release asset, not in normal Git history.
4. Replace the placeholder author name with the author name you want displayed publicly.
5. Enable Actions and run the workflow manually once to check the report.
6. Create a signed tag for each release and publish the SHA-256 from `release_summary.json`.

The monitor searches public GitHub code for distinctive phrases. It cannot see private repositories,
non-indexed file hosts, or copies that rewrite every phrase, so treat matches as leads for manual review.

