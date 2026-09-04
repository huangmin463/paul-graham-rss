# Paul Graham RSS

A dependency-free daily RSS scraper for the essay index at:

`https://paulgraham.com/articles.html`

The feed contains the current essay titles and canonical links. Each item uses
the first-seen time recorded in `feed-state.json`, because the index itself
does not publish dates. This is sufficient for RSS readers to detect new
essays without pretending that the source provides publication metadata.

## Run locally

From this directory:

```text
py scrape_feed.py --output feed.xml --state feed-state.json
```

Then open `feed.xml` in an RSS reader that supports local files, or serve the
directory with a local HTTP server:

```text
py -m http.server 8000
```

The local feed URL is `http://localhost:8000/feed.xml`.

Run the tests with:

```text
py -m unittest discover -s tests -v
```

## Publish it daily with GitHub Pages

1. Create a GitHub repository and copy the contents of this folder into its
   root.
2. In the repository, open **Settings → Pages**, choose **GitHub Actions** as
   the source, and allow the `github-pages` environment created by the
   workflow.
3. Optional: create a repository variable named `RSS_FEED_URL` containing the
   final URL, for example:

   `https://YOUR-NAME.github.io/YOUR-REPOSITORY/feed.xml`

   For a `YOUR-NAME.github.io` user-site repository, use:

   `https://YOUR-NAME.github.io/feed.xml`

4. Run **Actions → Update Paul Graham RSS → Run workflow** once. The workflow
   then runs every day at 17:00 UTC (01:00 China Standard Time), commits the
   state and generated feed, and deploys `public/feed.xml`.

Subscribe to the deployed `feed.xml` URL in your RSS reader.

## Notes

- The scraper refuses to overwrite the feed if the source page returns zero
  recognized essay links. This protects the feed from a transient block or a
  major source-page redesign.
- RSS item GUIDs are the canonical essay URLs, so they remain stable across
  runs.
- The feed links to the original essays and does not republish their full text.
  That keeps the scraper light and avoids storing a second copy of the essay
  content.
