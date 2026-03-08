#!/usr/bin/env python3
"""
Jira Epic & GitLab MR Commit Downloader  (resumable)

Downloads Jira epics matching text in their description, then finds all
GitLab Merge Request links in comments on those epics and their child
work items, and fetches the commits from each MR via the GitLab API.

Progress is check-pointed after every epic and every MR so the script can
be interrupted and resumed at any time without re-downloading completed work.

Output layout
─────────────
<output-dir>/
  epics/                  one JSON file per Jira epic key  (e.g. PROJ-12.json)
  mrs/                    one JSON file per MR URL slug    (e.g. mygroup__repo__42.json)
  jira_progress.json      set of completed epic keys
  gitlab_progress.json    {"done": [...urls], "failed": [...urls]}
  mr_refs.json            mr_url → [jira issue keys]  (written after Jira phase)
  merge_requests.json     final merged MR list  (written at end)
  commits.json            final merged commit list, deduplicated  (written at end)

Usage
─────
  python jira_git_downloader.py \\
      --project MYPROJ \\
      --search  "payment gateway" \\
      --jira-url   https://myorg.atlassian.net \\
      --jira-user  me@example.com \\
      --jira-token <JIRA_API_TOKEN> \\
      --gitlab-token <GITLAB_ACCESS_TOKEN> \\
      [--gitlab-url  https://gitlab.com] \\
      [--output-dir  ./output] \\
      [--retries 5] \\
      [--retry-delay 2.0] \\
      [--timeout 30]

Re-run the same command to resume after a failure.
Pass --rebuild-final to re-merge individual files into the aggregated outputs
without re-fetching anything.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    tmp.replace(path)   # atomic replace — avoids corrupt checkpoints on crash


def mr_url_to_slug(mr_url: str) -> str:
    """Turn an MR URL into a filesystem-safe filename stem."""
    parsed = urlparse(mr_url)
    project_path = parsed.path.split("/-/")[0].lstrip("/")
    mr_iid = GITLAB_MR_RE.search(mr_url).group(1)
    slug = project_path.replace("/", "__") + "__" + mr_iid
    # Remove any character that is not safe on all platforms
    slug = re.sub(r'[^\w\-.]', '_', slug)
    return slug


# ─────────────────────────────────────────────────────────────────────────────
# Retry-aware HTTP helper
# ─────────────────────────────────────────────────────────────────────────────

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def retry_get(session: requests.Session, url: str, params: dict = None,
              retries: int = 5, base_delay: float = 2.0,
              timeout: int = 30) -> requests.Response:
    """
    GET *url* with exponential backoff on transient errors.
    Raises the last exception if all retries are exhausted.
    Respects Retry-After header on 429 responses.
    """
    delay = base_delay
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code in RETRYABLE_STATUS:
                retry_after = int(resp.headers.get("Retry-After", delay))
                wait = max(retry_after, delay)
                print(f"  [retry] HTTP {resp.status_code} — waiting {wait:.1f}s "
                      f"(attempt {attempt}/{retries})")
                time.sleep(wait)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            print(f"  [retry] {type(exc).__name__} — waiting {delay:.1f}s "
                  f"(attempt {attempt}/{retries})")
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"All {retries} retries exhausted for {url}") from last_exc


# ─────────────────────────────────────────────────────────────────────────────
# Jira helpers
# ─────────────────────────────────────────────────────────────────────────────

def jira_get(session, base_url, path, params=None, **kw):
    url = f"{base_url.rstrip('/')}/rest/api/3/{path.lstrip('/')}"
    return retry_get(session, url, params=params, **kw).json()


def jira_search_jql(session, base_url, jql_query, fields, **http_kw) -> list:
    """Paginate /rest/api/3/search/jql using nextPageToken cursor."""
    issues = []
    params = {
        "jql": jql_query,
        "maxResults": 50,
        "fields": fields,
    }
    while True:
        data = jira_get(session, base_url, "search/jql", params, **http_kw)
        batch = data.get("issues", [])
        issues.extend(batch)
        next_token = data.get("nextPageToken")
        if not next_token or not batch:
            break
        params["nextPageToken"] = next_token
    return issues


def search_epics(session, base_url, project, search_text, **http_kw):
    jql = f'project = "{project}" AND issuetype = "Epic" AND statusCategory = "Done" AND cf[11232] ~ "{search_text}"'
    print(f"[Jira] JQL: {jql}")
    epics = jira_search_jql(session, base_url, jql,
                            "summary,description,status,assignee,created,updated,customfield_11232",
                            **http_kw)
    print(f"[Jira] Found {len(epics)} epic(s).")
    return epics


def get_child_issues(session, base_url, epic_key, **http_kw):
    jql = f'"Epic Link" = {epic_key} OR parent = {epic_key}'
    return jira_search_jql(session, base_url, jql, "summary,status,comment", **http_kw)


def get_comments(session, base_url, issue_key, **kw):
    comments, start_at = [], 0
    while True:
        data = jira_get(session, base_url, f"issue/{issue_key}/comment",
                        {"startAt": start_at, "maxResults": 50}, **kw)
        batch = data.get("comments", [])
        comments.extend(batch)
        start_at += len(batch)
        if start_at >= data.get("total", 0):
            break
    return comments


def comment_body_to_text(comment: dict) -> str:
    body = comment.get("body", "")
    return body if isinstance(body, str) else _adf_to_text(body)


def _adf_to_text(node) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    parts = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for mark in node.get("marks", []):
        if mark.get("type") == "link":
            href = mark.get("attrs", {}).get("href", "")
            if href:
                parts.append(href)
    if node.get("type") in ("inlineCard", "blockCard", "embedCard"):
        url = node.get("attrs", {}).get("url", "")
        if url:
            parts.append(url)
    for child in node.get("content", []):
        parts.append(_adf_to_text(child))
    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# GitLab MR link extraction
# ─────────────────────────────────────────────────────────────────────────────

GITLAB_MR_RE = re.compile(
    r'https?://[^\s"\'<>]+/-/merge_requests/(\d+)', re.IGNORECASE)


def extract_mr_links(text: str) -> list[tuple[str, int]]:
    results, seen = [], set()
    for m in GITLAB_MR_RE.finditer(text):
        mr_url = m.group(0).rstrip(".,;)")
        if mr_url not in seen:
            seen.add(mr_url)
            results.append((mr_url, int(m.group(1))))
    return results


def mr_url_to_project_path_encoded(mr_url: str) -> str:
    parsed = urlparse(mr_url)
    project_path = parsed.path.split("/-/")[0].lstrip("/")
    return requests.utils.quote(project_path, safe="")


# ─────────────────────────────────────────────────────────────────────────────
# GitLab API helpers
# ─────────────────────────────────────────────────────────────────────────────

def gitlab_get_paged(session, gitlab_base, path, params=None, **kw) -> list:
    results, page = [], 1
    while True:
        url = f"{gitlab_base.rstrip('/')}/api/v4/{path.lstrip('/')}"
        resp = retry_get(session, url,
                         params={**(params or {}), "per_page": 100, "page": page},
                         **kw)
        batch = resp.json()
        if not batch:
            break
        results.extend(batch)
        next_page = resp.headers.get("x-next-page", "")
        if not next_page:
            break
        page = int(next_page)
    return results


def gitlab_get_one(session, gitlab_base, path, **kw) -> dict:
    url = f"{gitlab_base.rstrip('/')}/api/v4/{path.lstrip('/')}"
    return retry_get(session, url, **kw).json()


def get_mr_info(session, gitlab_base, project_encoded, mr_iid, **kw):
    return gitlab_get_one(
        session, gitlab_base,
        f"projects/{project_encoded}/merge_requests/{mr_iid}", **kw)


def get_mr_commits(session, gitlab_base, project_encoded, mr_iid, **kw):
    return gitlab_get_paged(
        session, gitlab_base,
        f"projects/{project_encoded}/merge_requests/{mr_iid}/commits", **kw)


def get_commit_diffs(session, gitlab_base, project_encoded, sha, **kw):
    return gitlab_get_paged(
        session, gitlab_base,
        f"projects/{project_encoded}/repository/commits/{sha}/diff", **kw)


def _is_binary_diff(diff_str: str) -> bool:
    """Return True if the diff has no +/- content lines (binary or empty)."""
    if not diff_str:
        return True
    return not any(
        l.startswith('+') or l.startswith('-')
        for l in diff_str.splitlines()
        if not l.startswith('+++') and not l.startswith('---')
    )


def _compress_diff(diff_str: str, max_chars: int = 3000) -> str:
    """Strip context lines and cap diff at max_chars."""
    if len(diff_str) <= max_chars:
        return diff_str
    lines = diff_str.splitlines(keepends=True)
    filtered = [
        l for l in lines
        if l.startswith(('+', '-', '@@', 'diff ', 'index '))
    ]
    compressed = "".join(filtered)
    if len(compressed) > max_chars:
        compressed = compressed[:max_chars] + "\n[... diff truncated ...]\n"
    return compressed


def _process_diff_files(raw_diffs: list, per_file_cap: int = 3000,
                        per_commit_cap: int = 8000) -> list:
    """Process raw GitLab diff objects with size management."""
    result = []
    total_chars = 0

    for d in raw_diffs:
        diff_str = d.get("diff", "")
        if _is_binary_diff(diff_str):
            continue   # skip binary files

        compressed = _compress_diff(diff_str, per_file_cap)
        entry = {
            "old_path":     d.get("old_path"),
            "new_path":     d.get("new_path"),
            "new_file":     d.get("new_file", False),
            "renamed_file": d.get("renamed_file", False),
            "deleted_file": d.get("deleted_file", False),
            "diff":         compressed,
        }
        total_chars += len(compressed)
        result.append(entry)

        if total_chars > per_commit_cap:
            remaining = len(raw_diffs) - len(result)
            if remaining > 0:
                result.append({"note": f"[... {remaining} more file(s) truncated due to size limit ...]"})
            break

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Jira: fetch epics + children + comments, extract MR links
# ─────────────────────────────────────────────────────────────────────────────

def run_jira_phase(jira_session, args, output_dir: Path) -> dict[str, list[str]]:
    """
    Returns mr_refs: {mr_url: [jira_issue_key, ...]}

    Each completed epic is saved to epics/<KEY>.json.
    jira_progress.json records which keys are done so we can skip on resume.
    mr_refs.json is written (and updated) after each epic.
    """
    epics_dir = output_dir / "epics"
    epics_dir.mkdir(exist_ok=True)

    progress_path = output_dir / "jira_progress.json"
    mr_refs_path  = output_dir / "mr_refs.json"

    done_keys: set[str] = set(load_json(progress_path, []))
    mr_refs: dict[str, list[str]] = load_json(mr_refs_path, {})

    http_kw = dict(retries=args.retries, base_delay=args.retry_delay, timeout=args.timeout)

    # --- discover all matching epics (cheap, always re-run so list stays fresh) ---
    all_epics = search_epics(jira_session, args.jira_url, args.project, args.search, **http_kw)
    save_json([e["key"] for e in all_epics], output_dir / "epic_keys.json")

    total = len(all_epics)
    for idx, epic in enumerate(all_epics, 1):
        epic_key = epic["key"]
        if epic_key in done_keys:
            print(f"[Jira] ({idx}/{total}) {epic_key} — already done, skipping.")
            continue

        print(f"\n[Jira] ({idx}/{total}) Processing {epic_key}: "
              f"{epic['fields'].get('summary', '')}")

        try:
            epic_comments = get_comments(jira_session, args.jira_url, epic_key, **http_kw)
            children      = get_child_issues(jira_session, args.jira_url, epic_key, **http_kw)
            print(f"  └─ {len(children)} child issue(s), {len(epic_comments)} epic comment(s)")

            child_details = []
            for child in children:
                child_key      = child["key"]
                child_comments = get_comments(jira_session, args.jira_url, child_key, **http_kw)
                child_details.append({**child, "_fetched_comments": child_comments})

                for comment in child_comments:
                    for mr_url, _ in extract_mr_links(comment_body_to_text(comment)):
                        mr_refs.setdefault(mr_url, [])
                        if child_key not in mr_refs[mr_url]:
                            mr_refs[mr_url].append(child_key)

            for comment in epic_comments:
                for mr_url, _ in extract_mr_links(comment_body_to_text(comment)):
                    mr_refs.setdefault(mr_url, [])
                    if epic_key not in mr_refs[mr_url]:
                        mr_refs[mr_url].append(epic_key)

            save_json(
                {**epic, "_fetched_comments": epic_comments, "_children": child_details},
                epics_dir / f"{epic_key}.json",
            )

            done_keys.add(epic_key)
            save_json(sorted(done_keys), progress_path)   # checkpoint
            save_json(mr_refs, mr_refs_path)               # keep mr_refs current

        except Exception as exc:
            print(f"  ✗ Failed processing {epic_key}: {exc}")
            print("    (will retry on next run)")
            # continue with remaining epics; this one stays out of done_keys

    print(f"\n[Jira] Phase complete. "
          f"{len(done_keys)}/{total} epics processed. "
          f"{len(mr_refs)} unique MR link(s) found.")
    return mr_refs


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — GitLab: fetch each MR + its commits
# ─────────────────────────────────────────────────────────────────────────────

def run_gitlab_phase(gl_session, args, output_dir: Path,
                     mr_refs: dict[str, list[str]]):
    """
    Each MR is saved to mrs/<slug>.json.
    gitlab_progress.json tracks done/failed URLs.
    """
    mrs_dir = output_dir / "mrs"
    mrs_dir.mkdir(exist_ok=True)

    progress_path = output_dir / "gitlab_progress.json"
    prog = load_json(progress_path, {"done": [], "failed": []})
    done_urls:   set[str] = set(prog["done"])
    failed_urls: set[str] = set(prog["failed"])

    http_kw = dict(retries=args.retries, base_delay=args.retry_delay, timeout=args.timeout)

    all_mr_urls = list(mr_refs.keys())
    total = len(all_mr_urls)

    for idx, mr_url in enumerate(all_mr_urls, 1):
        if mr_url in done_urls:
            print(f"[GitLab] ({idx}/{total}) already done — {mr_url}")
            continue

        slug = mr_url_to_slug(mr_url)
        try:
            project_encoded = mr_url_to_project_path_encoded(mr_url)
            mr_iid          = int(GITLAB_MR_RE.search(mr_url).group(1))
            project_path    = requests.utils.unquote(project_encoded)

            print(f"\n[GitLab] ({idx}/{total}) MR !{mr_iid} — {project_path}")

            mr_info    = get_mr_info(gl_session, args.gitlab_url,
                                     project_encoded, mr_iid, **http_kw)
            mr_commits = get_mr_commits(gl_session, args.gitlab_url,
                                        project_encoded, mr_iid, **http_kw)

            print(f"  title  : {mr_info.get('title', '(unknown)')}")
            print(f"  state  : {mr_info.get('state')}")
            print(f"  commits: {len(mr_commits)}")

            # Fetch per-commit diffs
            commit_dicts = []
            skip_diffs = getattr(args, 'skip_diffs', False)
            for ci, c in enumerate(mr_commits, 1):
                sha = c.get("id", "")
                diff_files = []
                if sha and not skip_diffs:
                    print(f"  diff   : commit {ci}/{len(mr_commits)} {c.get('short_id', sha[:8])}")
                    try:
                        raw_diffs = get_commit_diffs(
                            gl_session, args.gitlab_url,
                            project_encoded, sha, **http_kw)
                        diff_files = _process_diff_files(raw_diffs)
                    except Exception as diff_exc:
                        print(f"    [warn] diff fetch failed: {diff_exc}")

                commit_dicts.append({
                    "id":              c.get("id"),
                    "short_id":        c.get("short_id"),
                    "title":           c.get("title"),
                    "message":         c.get("message"),
                    "author_name":     c.get("author_name"),
                    "author_email":    c.get("author_email"),
                    "authored_date":   c.get("authored_date"),
                    "committer_name":  c.get("committer_name"),
                    "committer_email": c.get("committer_email"),
                    "committed_date":  c.get("committed_date"),
                    "web_url":         c.get("web_url"),
                    "diff_files":      diff_files,
                })

            payload = {
                "mr_url": mr_url,
                "referenced_by_jira": sorted(mr_refs[mr_url]),
                "mr_iid": mr_iid,
                "project_path": project_path,
                "title":         mr_info.get("title"),
                "state":         mr_info.get("state"),
                "author":        mr_info.get("author", {}).get("username"),
                "created_at":    mr_info.get("created_at"),
                "merged_at":     mr_info.get("merged_at"),
                "web_url":       mr_info.get("web_url"),
                "source_branch": mr_info.get("source_branch"),
                "target_branch": mr_info.get("target_branch"),
                "commits":       commit_dicts,
            }
            save_json(payload, mrs_dir / f"{slug}.json")

            done_urls.add(mr_url)
            failed_urls.discard(mr_url)   # clear any previous failure

        except Exception as exc:
            status = ""
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                status = f" (HTTP {exc.response.status_code})"
            print(f"  ✗ Failed{status}: {exc}")
            failed_urls.add(mr_url)

        finally:
            save_json({"done": sorted(done_urls), "failed": sorted(failed_urls)},
                      progress_path)

    n_failed = len(failed_urls)
    print(f"\n[GitLab] Phase complete. "
          f"{len(done_urls)}/{total} MRs fetched, {n_failed} failed.")
    if n_failed:
        print(f"  Failed URLs written to {progress_path} — re-run to retry them.")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Merge individual files into final aggregated outputs
# ─────────────────────────────────────────────────────────────────────────────

def run_merge_phase(output_dir: Path):
    """Combine all mrs/*.json into merge_requests.json and commits.json."""
    mrs_dir = output_dir / "mrs"
    all_mrs, all_commits = [], []
    seen_commit_ids: set[str] = set()

    mr_files = sorted(mrs_dir.glob("*.json"))
    print(f"\n[Merge] Aggregating {len(mr_files)} MR file(s)…")

    for mr_file in mr_files:
        data = load_json(mr_file, {})
        mr_url       = data.get("mr_url", "")
        mr_iid       = data.get("mr_iid")
        project_path = data.get("project_path", "")
        jira_issues  = data.get("referenced_by_jira", [])
        commits      = data.get("commits", [])

        all_mrs.append({k: v for k, v in data.items() if k != "commits"} |
                       {"commit_count": len(commits)})

        for c in commits:
            cid = c.get("id", "")
            if cid in seen_commit_ids:
                continue
            seen_commit_ids.add(cid)
            all_commits.append({
                **c,
                "from_mr_url":  mr_url,
                "from_mr_iid":  mr_iid,
                "project_path": project_path,
                "jira_issues":  jira_issues,
            })

    save_json(all_mrs,    output_dir / "merge_requests.json")
    save_json(all_commits, output_dir / "commits.json")
    print(f"[Merge] {len(all_mrs)} MRs, {len(all_commits)} unique commits written.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Required
    parser.add_argument("--project",       required=True, help="Jira project key")
    parser.add_argument("--search",        required=True, help="Text to match in epic descriptions")
    parser.add_argument("--jira-url",      required=True, help="Jira base URL")
    # Optional
    parser.add_argument("--gitlab-url",    default="https://gitlab.com",
                        help="GitLab instance URL (default: https://gitlab.com)")
    parser.add_argument("--output-dir",    default="./jira_output",
                        help="Root output directory (default: ./jira_output)")
    parser.add_argument("--retries",       type=int,   default=5,
                        help="Max retries per HTTP request (default: 5)")
    parser.add_argument("--retry-delay",   type=float, default=2.0,
                        help="Initial retry back-off in seconds (default: 2.0, doubles each attempt)")
    parser.add_argument("--timeout",       type=int,   default=30,
                        help="HTTP request timeout in seconds (default: 30)")
    parser.add_argument("--skip-jira",     action="store_true",
                        help="Skip Jira phase and use existing mr_refs.json")
    parser.add_argument("--skip-gitlab",   action="store_true",
                        help="Skip GitLab fetch phase (only re-merge existing files)")
    parser.add_argument("--rebuild-final", action="store_true",
                        help="Only re-merge mrs/*.json → merge_requests.json + commits.json")
    parser.add_argument("--skip-diffs", action="store_true",
                        help="Skip per-commit diff download (faster runs or re-merging)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --rebuild-final: just re-aggregate, no network calls
    if args.rebuild_final:
        run_merge_phase(output_dir)
        return

    # --- Jira session ---
    jira_session = requests.Session()
    jira_session.auth = HTTPBasicAuth(os.getenv("JIRA_USERNAME"), os.getenv("JIRA_API_TOKEN"))
    jira_session.headers.update({"Accept": "application/json"})

    # --- GitLab session ---
    gl_session = requests.Session()
    gl_session.headers.update({
        "PRIVATE-TOKEN": os.getenv("GIT_API_TOKEN"),
        "Accept": "application/json",
    })

    # Phase 1 — Jira
    if args.skip_jira:
        mr_refs_path = output_dir / "mr_refs.json"
        if not mr_refs_path.exists():
            print("ERROR: --skip-jira requested but mr_refs.json not found.", file=sys.stderr)
            sys.exit(1)
        mr_refs = load_json(mr_refs_path, {})
        print(f"[Jira] Skipped — loaded {len(mr_refs)} MR refs from {mr_refs_path}")
    else:
        mr_refs = run_jira_phase(jira_session, args, output_dir)

    if not mr_refs:
        print("No MR links found. Exiting.")
        sys.exit(0)

    # Phase 2 — GitLab
    if not args.skip_gitlab:
        run_gitlab_phase(gl_session, args, output_dir, mr_refs)

    # Phase 3 — Merge
    run_merge_phase(output_dir)

    print(f"\n✅ All done. Output: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
