# Privacy policy

Effective 2026-11-24.

Zabob Retirement is free, open-source software that runs on your own
computer. Nobody operates it as a service. It has no accounts and no
analytics, and it sends nothing to its developer. This policy describes what
the software does with your data, including the video publishing tool that uses
the YouTube API Services.

## Your planning data

Everything you enter, such as accounts, balances, spending, people and
scenarios, stays in files on your computer: your data repository and the
`state/` folder of simulation results. The software doesn't upload them
anywhere. If you put your data repository on a hosting service such as
GitHub, that's your choice, and that service's own policy applies.

A few commands go to public data sources when you run them, and send only
what is needed to ask:

- `sim prices fetch` asks Yahoo Finance for the prices of the ticker symbols
  you name. Only the symbols leave your computer, not your holdings or
  balances.
- `sim historical` downloads public economic series from the U.S.
  Bureau of Labor Statistics, the Bureau of Economic Analysis, FRED and
  NYU Stern. The BLS refuses requests without contact details, so these
  requests carry the email address you give it (`--contact`, or your
  `git config user.email`).

Installing and updating the software downloads it and its dependencies from
GitHub and the Python package index.

## YouTube API Services

This section applies only if you fork the project and choose to upload your
own videos to your own YouTube channel. Using the simulator, or watching the
project's videos, never involves it.

The project's instructional videos are published with a tool in this
repository (`analysis video publish`) that uses the YouTube API Services.
If you use it, you agree to be bound by the
[YouTube Terms of Service](https://www.youtube.com/t/terms), and Google's
handling of your data is governed by the
[Google Privacy Policy](https://policies.google.com/privacy). It acts only
on the channel you sign in to, with your own Google API project. When you
run it:

- **What it accesses.** You sign in with Google (OAuth) and grant it access
  to your YouTube account. It uses that access only to upload the videos you
  tell it to, with their captions and thumbnails; to set their titles,
  descriptions and tags; to list your own playlists, to find the one a video
  belongs in; and to add videos to it. It doesn't read your viewing history,
  subscribers, comments, analytics or any other channel's data.
- **What it stores.** The sign-in token is saved on your computer, in your
  configuration folder (`~/.config/analysis-videos/token.json` unless you
  set `ZABOB_VIDEO_SECRETS`), readable only by you. The IDs of the videos
  you uploaded, the length of each scene, and a hash of the title and
  description last sent are written to `published.toml` files beside the
  video scripts.
- **Who it shares with.** Nobody. The data goes only between your computer
  and Google. The developer never receives your token or any of your data.
- **Revoking access.** Delete the token file, and remove the app's access in
  your Google account's
  [security settings](https://security.google.com/settings/security/permissions).
- **Cookies.** The tool is a command-line program and uses no cookies. The
  Google sign-in page it opens in your browser is Google's, under Google's
  policy.

## Changes and contact

Changes to this policy are made in this file, and its history on GitHub
shows every version. Questions go to the project's
[GitHub issues](https://github.com/BobKerns/zabob-retirement/issues).
