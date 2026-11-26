#!/usr/bin/env python3
"""VPM リスティング(index.json)を生成する。

2 つの供給源を統合する:
1. mergeListings … 既存のホスト済みリスティング(PBReplacer-VPM / LipSyncSetter など)の
   packages をそのまま取り込む(各リポジトリ側の改修が不要)
2. githubRepos … 各リポジトリの GitHub Releases を走査し、アセットに
   package.json と {name}-{version}.zip の両方を持つリリースを登録する
   (NDMFDeform の release.yml が作る形式。該当アセットの無いリリースは安全にスキップ)

同名・同バージョンが両方にある場合はリリース走査の結果を優先する。
あわせて各バージョンの zip のダウンロード数(Releases API の download_count)を集計し、
日次の推移を downloads.json に記録する。履歴は STATS_DIR(ワークフローでは stats ブランチ)
の downloads.json に蓄積され、未指定ならその回の値だけを出力する。

出力: website/ に index.json / meta.json / downloads.json / site の静的ファイル一式。
依存: 標準ライブラリのみ。GITHUB_TOKEN があれば API レート制限が緩和される。
"""
import datetime
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "website")
STATS_FILE = "downloads.json"
# 日次の区切りに使うタイムゾーン(JST 固定。tzdata に依存しない)
STATS_TZ = datetime.timezone(datetime.timedelta(hours=9))
STATS_TZ_NAME = "Asia/Tokyo"


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


def normalize_manifest(manifest):
    """VCC(Newtonsoft)が読める形に manifest を揃える。

    VCC はパッケージ manifest の author を {name, email, url} のオブジェクトとして
    デシリアライズする。文字列だと例外になり、そのリスティング全体が
    "valid repository listing ではない" と拒否されるため、文字列は name に包む。
    """
    author = manifest.get("author")
    if isinstance(author, str):
        manifest["author"] = {"name": author}
    return manifest


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
                    target[version] = normalize_manifest(manifest)
                    added += 1
            print(f"merged: {name} +{added} versions from {url}")


def list_releases(repo):
    """リポジトリの全リリースをページ送りで取得する。"""
    releases = []
    page = 1
    while True:
        batch = api_json(
            f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def asset_key(url):
    """リスティング側の URL とリリースアセットの URL を突き合わせるためのキー。"""
    return urllib.parse.unquote(url or "")


def collect_release_packages(packages, github_repos):
    """リリースを走査して packages に登録し、全アセットのダウンロード数を返す。

    戻り値は {アセット URL: download_count}。mergeListings 由来のバージョンも
    zip は同じリポジトリのリリースアセットなので、URL で引けば数が取れる。
    """
    asset_counts = {}
    for repo in github_repos:
        try:
            releases = list_releases(repo)
        except Exception as error:  # リポジトリ単位の失敗はリスティング全体を壊さない
            print(f"warning: failed to list releases for {repo}: {error}", file=sys.stderr)
            continue

        for release in releases:
            if release.get("draft"):
                continue
            assets = {asset["name"]: asset for asset in release.get("assets", [])}
            for asset in assets.values():
                asset_counts[asset_key(asset.get("browser_download_url"))] = \
                    asset.get("download_count", 0)
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
            packages.setdefault(name, {"versions": {}})["versions"][version] = normalize_manifest(manifest)
            print(f"added: {name} {version} (from {repo})")
    return asset_counts


def update_download_stats(previous, packages, asset_counts, now):
    """前回の統計 previous に今回のダウンロード数を反映した統計を返す。

    - packages … 現在の累計(パッケージ合計とバージョン別)。offsets は、アセットの
      差し替えで GitHub 側のカウントが 0 に戻ったバージョンについて持ち越した数
    - history … 1 日 1 件。totals はパッケージ別累計、versions はその日に数が動いた
      バージョンだけの累計(初回は全バージョン)。同じ日に複数回実行したら上書きする

    今回数が取れなかったバージョン(API 失敗・リスティングから削除)は前回値を引き継ぎ、
    一時的な取得失敗で累計が落ち込んだように見えるのを防ぐ。
    変化が無ければ previous をそのまま返す。
    """
    prev_packages = previous.get("packages") or {}
    current = {}
    for name in sorted(set(prev_packages) | set(packages)):
        prev_entry = prev_packages.get(name) or {}
        versions = dict(prev_entry.get("versions") or {})
        offsets = dict(prev_entry.get("offsets") or {})
        for version, manifest in ((packages.get(name) or {}).get("versions") or {}).items():
            raw = asset_counts.get(asset_key(manifest.get("url")))
            if raw is None:
                continue
            before = versions.get(version, 0)
            if raw + offsets.get(version, 0) < before:
                # アセットが差し替えられて GitHub 側のカウントが 0 からやり直しになった。
                # それまでの数を offset として持ち越し、累計が途切れないようにする
                offsets[version] = before
                print(f"info: {name} {version}: download count restarted, carrying over {before}")
            versions[version] = raw + offsets.get(version, 0)
        if versions:
            current[name] = {"total": sum(versions.values()), "versions": versions}
            if offsets:
                current[name]["offsets"] = offsets

    if current == prev_packages:
        return previous

    changed = {}
    for name, entry in current.items():
        prev_versions = (prev_packages.get(name) or {}).get("versions") or {}
        diff = {v: c for v, c in entry["versions"].items() if prev_versions.get(v) != c}
        if diff:
            changed[name] = diff

    history = list(previous.get("history") or [])
    today = now.astimezone(STATS_TZ).strftime("%Y-%m-%d")
    totals = {name: entry["total"] for name, entry in current.items()}
    if history and history[-1].get("date") == today:
        entry = history[-1]
        merged = entry.get("versions") or {}
        for name, diff in changed.items():
            merged.setdefault(name, {}).update(diff)
        history[-1] = {"date": today, "totals": totals, "versions": merged}
    else:
        history.append({"date": today, "totals": totals, "versions": changed})

    return {
        "schema": 1,
        "timezone": STATS_TZ_NAME,
        "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packages": current,
        "history": history,
    }


def load_stats(stats_dir):
    if not stats_dir:
        return {}
    path = os.path.join(stats_dir, STATS_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data, indent=2):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent)
        handle.write("\n")


def main():
    with open(os.path.join(ROOT, "source.json"), encoding="utf-8") as handle:
        source = json.load(handle)

    packages = {}
    merge_existing_listings(packages, source.get("mergeListings", []))
    asset_counts = collect_release_packages(packages, source.get("githubRepos", []))

    now = datetime.datetime.now(datetime.timezone.utc)
    stats_dir = os.environ.get("STATS_DIR")
    previous_stats = load_stats(stats_dir)
    stats = update_download_stats(previous_stats, packages, asset_counts, now)

    # VCC はリスティングの author を文字列として読む(オブジェクトだと
    # "does not contain a valid repository listing" で追加に失敗する)
    author = source["author"]
    if isinstance(author, dict):
        author = author.get("name", "")

    index = {
        "name": source["name"],
        "id": source["id"],
        "url": source["url"],
        "author": author,
        "packages": packages,
    }
    if source.get("description"):
        index["description"] = source["description"]

    meta = {
        "listingName": source["name"],
        "description": source.get("description", ""),
        "packages": source.get("packagesMeta", {}),
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    shutil.copytree(os.path.join(ROOT, "site"), OUT_DIR)
    write_json(os.path.join(OUT_DIR, "index.json"), index)
    write_json(os.path.join(OUT_DIR, "meta.json"), meta)
    write_json(os.path.join(OUT_DIR, STATS_FILE), stats, indent=None)
    if stats_dir and stats is not previous_stats:
        os.makedirs(stats_dir, exist_ok=True)
        write_json(os.path.join(stats_dir, STATS_FILE), stats, indent=1)
        print(f"updated download stats ({len(stats['history'])} days of history)")

    total = sum(len(p["versions"]) for p in packages.values())
    print(f"wrote index.json ({len(packages)} packages, {total} versions)")


if __name__ == "__main__":
    main()
