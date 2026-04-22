#!/usr/bin/env python3
"""
merge_pr.py — merge a student PR into main
Usage: python merge_pr.py <PR_NUMBER>
"""

import subprocess
import sys
import json
from pathlib import Path


def run(cmd, check=True, capture=False):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if capture:
        return result
    if check and result.returncode != 0:
        print(f"\n❌ Command failed: {' '.join(cmd)}")
        sys.exit(1)
    return result


def run_capture(cmd):
    return run(cmd, check=False, capture=True)


def get_pr_info(pr_number):
    result = run_capture(["gh", "pr", "view", str(pr_number), "--json", "headRefName,author,title"])
    if result.returncode != 0:
        print(f"❌ Could not fetch PR #{pr_number} info.")
        sys.exit(1)
    data = json.loads(result.stdout)
    branch = data["headRefName"]
    author = data["author"]["login"]
    title = data["title"]
    return branch, author, title


def delete_local_branch(branch):
    result = run_capture(["git", "branch", "-D", branch])
    if result.returncode == 0:
        print(f"🗑  Deleted existing local branch: {branch}")
    # Not an error if it didn't exist


def check_pr_changes(pr_branch):
    result = run_capture(["git", "diff", "--name-status", "origin/main...HEAD"])
    lines = result.stdout.strip().split("\n")
    warnings = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]
        filename = parts[-1]
        if filename == "fakemon/fakemonlist.json":
            continue
        if status == "D":
            warnings.append(f"  ⛔ DELETES:  {filename}")
        elif status == "M":
            warnings.append(f"  ⚠️  MODIFIES: {filename}")
        elif status == "R":
            old_name = parts[1] if len(parts) > 1 else "?"
            warnings.append(f"  ⚠️  RENAMES:  {old_name} → {filename}")
    if warnings:
        print("\n🚨 PR WARNING — unexpected changes detected:")
        for w in warnings:
            print(w)
        answer = input("\nContinue anyway? (y/n): ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)
    else:
        print("\n✅ PR looks clean — only additions and fakemonlist.json changes.")


def sync_fakemonlist():
    fakemon_dir = Path("fakemon")
    output_file = fakemon_dir / "fakemonlist.json"
    files = sorted([
        f.stem for f in fakemon_dir.glob("*.json")
        if f.name != "fakemonlist.json"
    ])
    with open(output_file, "w") as f:
        json.dump({"fakemon": files}, f, indent=2)
    print(f"\n📋 Updated fakemonlist.json with {len(files)} fakemon:")
    for name in files:
        print(f"   {name}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python merge_pr.py <PR_NUMBER>")
        sys.exit(1)

    pr_number = sys.argv[1]
    local_branch = f"pr-{pr_number}"

    print(f"\n{'='*55}")
    print(f"  Merging PR #{pr_number}")
    print(f"{'='*55}")

    # Get PR metadata
    pr_branch, author, title = get_pr_info(pr_number)
    print(f"\n  Title:   {title}")
    print(f"  Branch:  {pr_branch}")
    print(f"  Author:  {author}")

    # Clean up any existing local branch
    delete_local_branch(local_branch)

    # Fetch and checkout
    run(["git", "fetch", "origin", f"pull/{pr_number}/head:{local_branch}"])
    run(["git", "checkout", local_branch])

    # Merge origin/main in
    print(f"\n$ git merge origin/main")
    result = subprocess.run(["git", "merge", "origin/main"], text=True)

    if result.returncode != 0:
        print("\n⚠️  Merge conflict detected!")
        print("Fix the conflicts, then press Enter to continue...")
        input()

    # Check for suspicious file changes
    check_pr_changes(local_branch)

    # Sync fakemonlist.json
    sync_fakemonlist()

    # Stage and commit
    run(["git", "add", "-A"])

    commit_msg = f"merge ({pr_number}, {pr_branch}, {author})"
    result = run_capture(["git", "commit", "-m", commit_msg])
    if result.returncode == 0:
        print(f"\n✅ Committed: {commit_msg}")
    else:
        if "nothing to commit" in result.stdout + result.stderr:
            print("\n✅ Nothing new to commit — already clean.")
        else:
            print(result.stdout)
            print(result.stderr)

    # Merge into main and push
    run(["git", "checkout", "main"])
    run(["git", "merge", local_branch])
    run(["git", "push", "origin", "main"])

    print(f"\n🐉 PR #{pr_number} ({title}) merged successfully!\n")


if __name__ == "__main__":
    main()