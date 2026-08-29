#!/usr/bin/env python3
"""VPM リスティング(index.json)を生成する。

2 つの供給源を統合する:
1. mergeListings … 既存のホスト済みリスティング(PBReplacer-VPM / LipSyncSetter など)の
   packages をそのまま取り込む(各リポジトリ側の改修が不要)
2. githubRepos … 各リポジトリの GitHub Releases を走査し、アセットに
   package.json と {name}-{version}.zip の両方を持つリリースを登録する
   (NDMFDeform の release.yml が作る形式。該当アセットの無いリリースは安全にスキップ)

同名・同バージョンが両方にある場合はリリース走査の結果を優先する。
出力: website/ に index.json / meta.json / site の静的ファイル一式。
依存: 標準ライブラリのみ。GITHUB_TOKEN があれば API レート制限が緩和される。
"""
import datetime
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "website")


def request(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "vpm-listing-builder",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers))


def api_json(url):
    with request(url) as response:
        return json.load(response)


def fetch_json(url):
    with request(url) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def merge_existing_listings(packages, listing_urls):
    for url in listing_urls:
        try:
            listing = fetch_json(url)
        except Exception as error:
            print(f"warning: failed to fetch listing {url}: {error}", file=sys.stderr)
            continue
        for name, entry in (listing.get("packages") or {}).items():
            versions = entry.get("versions") or {}
            target = packages.setdefault(name, {"versions": {}})["versions"]
            added = 0
            for version, manifest in versions.items():
                if version not in target:
                    target[version] = manifest
                    added += 1
            print(f"merged: {name} +{added} versions from {url}")


def collect_release_packages(packages, github_repos):
    for repo in github_repos:
        try:
            releases = api_json(f"https://api.github.com/repos/{repo}/releases?per_page=100")
        except Exception as error:  # リポジトリ単位の失敗はリスティング全体を壊さない
            print(f"warning: failed to list releases for {repo}: {error}", file=sys.stderr)
            continue

        for release in releases:
            if release.get("draft"):
                continue
            assets = {asset["name"]: asset for asset in release.get("assets", [])}
            manifest_asset = assets.get("package.json")
            if manifest_asset is None:
                continue

            try:
                manifest = fetch_json(manifest_asset["browser_download_url"])
            except Exception as error:
                print(f"warning: failed to read manifest of {repo}@{release.get('tag_name')}: {error}",
                      file=sys.stderr)
                continue

            name = manifest.get("name")
            version = manifest.get("version")
            if not name or not version:
                continue

            zip_asset = assets.get(f"{name}-{version}.zip")
            if zip_asset is None:
                print(f"info: {repo}@{release.get('tag_name')}: no {name}-{version}.zip asset, skipped",
                      file=sys.stderr)
                continue

            manifest["url"] = zip_asset["browser_download_url"]
            # リリース走査の結果を既存リスティング由来より優先する
            packages.setdefault(name, {"versions": {}})["versions"][version] = manifest
            print(f"added: {name} {version} (from {repo})")


def main():
    with open(os.path.join(ROOT, "source.json"), encoding="utf-8") as handle:
        source = json.load(handle)

    packages = {}
    merge_existing_listings(packages, source.get("mergeListings", []))
    collect_release_packages(packages, source.get("githubRepos", []))

    index = {
        "name": source["name"],
        "id": source["id"],
        "url": source["url"],
        "author": source["author"],
        "packages": packages,
    }
    if source.get("description"):
        index["description"] = source["description"]

    meta = {
        "listingName": source["name"],
        "description": source.get("description", ""),
        "packages": source.get("packagesMeta", {}),
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    shutil.copytree(os.path.join(ROOT, "site"), OUT_DIR)
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with open(os.path.join(OUT_DIR, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    total = sum(len(p["versions"]) for p in packages.values())
    print(f"wrote index.json ({len(packages)} packages, {total} versions)")


if __name__ == "__main__":
    main()
