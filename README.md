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
- `scripts/build_listing.py` … 上記を統合して `website/index.json` と `meta.json` を生成。
  あわせてダウンロード数を集計して `downloads.json` を出力する(下記)
- `site/` … ランディングページ(index.json を動的に読み込んで表示。URL はページ位置から
  自動算出するため、リポジトリ名を変えても `source.json` の `url` 以外の修正は不要)
- `.github/workflows/build-listing.yml` … push / 6時間ごと / 手動実行で生成し GitHub Pages へデプロイ

## ダウンロード数の記録

各バージョンの zip は GitHub Releases のアセットなので、Releases API の `download_count`
(累計値)をビルドのたびに読み取り、日次の推移として記録しています。

- 履歴の保存先は **`stats` ブランチの `downloads.json`**(初回実行時にワークフローが自動作成)。
  Pages は毎回作り直されるため、履歴だけ別ブランチに積んでいます
- 公開先: https://c-colloid.github.io/vpm/downloads.json (ランディングページのカードに
  累計・直近 30 日の日別グラフ・バージョン別の内訳を表示)
- `packages` … 現在の累計(パッケージ合計 `total` とバージョン別 `versions`)
- `history` … 1 日 1 件(日付は JST)。`totals` はパッケージ別の累計、`versions` はその日に
  数が動いたバージョンだけの累計(初回は全バージョン)。どのパッケージも動かなかった日は
  記録されないので、欠けている日は「増加 0」として読む

数字の注意点:

- 記録開始より前の推移は取れない(API が返すのは累計のみ)
- VCC / ALCOM のキャッシュにより同じバージョンの再導入は数えられず、一方でブラウザからの
  手動ダウンロードやボットの取得は含まれる。ユニークユーザー数ではない
- リリースのアセットを差し替えると GitHub 側のカウントは 0 に戻るが、それまでの数を
  `offsets` に持ち越して合算するので、記録上の累計は途切れない

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
