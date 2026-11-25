# Historical workflows — not active build/release entry points

These five workflows were moved byte-for-byte out of `.github/workflows/`.
Their `.disabled` extension is intentional: do not copy them back or dispatch
old experimental branches for a normal App release.

The single compiler/publisher is `.github/workflows/openminis-app.yml`,
using fixed branch `ios15-160652-four-features` and feed `beta-latest`.
`upstream-watch.yml` sends notifications and updates watcher state; it neither
compiles nor publishes an App and is not a second compiler/channel.

GitHub still keeps historical workflow IDs and run logs. After separate user
approval, ALL eight historical compiler IDs must be disabled server-side:
369039789, 369847715, 369582544, 376725893, 429010557, 428580423, 369143684,
384811054. The last ID's old runs contain destructive release deletion code:
keeping that ID enabled would still permit rerunning the old implementation.
Do not delete runs, releases, tags, old IPA assets or source branches.
The new permanent compiler ID must be checked after the first authorized push.
Remote disable has NOT happened in this local-only candidate.
The watcher ID 370938304 is unrelated to compilation.

The source snapshot contains current lyrics/daily-action changes; App source
and the phone update URL were not changed by this workflow consolidation.
