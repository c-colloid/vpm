# ｺﾛｲﾄﾞのVPMパッケージ (c-colloid/vpm)

colloid が配布するパッケージ(NDMFDeform / UITKFontFix / PBReplacer / LipSyncSetter / …)の
統合 VPM リスティングです。

## 利用者向け

VCC / ALCOM に次の URL をリポジトリとして追加してください:

```
https://c-colloid.github.io/vpm/index.json
```

ランディングページ: https://c-colloid.github.io/vpm/

## 仕組み

- `source.json` … リスティングのメタデータ・収集対象の設定
  - `githubRepos` … GitHub Releases を走査するリポジトリ。アセットに `package.json` と
    `{パッケージ名}-{バージョン}.zip` の両方を持つリリースだけが登録される
    (NDMFDeform の `release.yml` が作る形式。該当なしのリリースは安全にスキップ)
  - `mergeListings` … 既存のホスト済みリスティング(PBReplacer-VPM / LipSyncSetter)を
    そのまま取り込む。**各リポジトリ側の改修は不要**。同名同バージョンはリリース走査を優先
  - `packagesMeta` … ランディングページに表示するドキュメント / GitHub リンク
- `scripts/build_listing.py` … 上記を統合して `website/index.json` と `meta.json` を生成
- `site/` … ランディングページ(index.json を動的に読み込んで表示。URL はページ位置から
  自動算出するため、リポジトリ名を変えても `source.json` の `url` 以外の修正は不要)
- `.github/workflows/build-listing.yml` … push / 6時間ごと / 手動実行で生成し GitHub Pages へデプロイ

## 初回セットアップ

1. この内容を `c-colloid/vpm` の `main` へ push
2. Settings > Pages > Build and deployment > Source を **GitHub Actions** にする
3. Actions タブから `Build listing` を一度手動実行(以後はリリースの度に自動追従)

## パッケージを追加するには

- リリース走査型: `source.json` の `githubRepos` にリポジトリを追記し、そのリポジトリの
  リリースに `package.json` + `{name}-{version}.zip` をアセット添付する
  (NDMFDeform の `.github/workflows/release.yml` 参照)
- 既存リスティング型: 配信中の listing JSON の URL を `mergeListings` に追記する

ドキュメントリンクは `packagesMeta` に追記するとカードに表示されます。
