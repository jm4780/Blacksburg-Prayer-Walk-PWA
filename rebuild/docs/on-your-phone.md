# Open it on your phone

Nothing to install. You click a few buttons on the GitHub website, wait, and get
a link to open on your phone.

**About 10 minutes**, nearly all of it waiting.

This creates a temporary computer that GitHub runs for you, free within a monthly
allowance you are very unlikely to reach. It sleeps when you stop using it, and
you can delete it when you are done.

---

## 1. Start the computer

1. Open this repository on GitHub.
2. Set the branch selector near the top left to
   **`claude/blacksburg-prayer-walk-pwa-mr0wro`**.
3. Click the green **`< > Code`** button, then the **Codespaces** tab.
4. Click the **three dots (`...`)**, then **New with options...**
5. Where it says **Dev container configuration**, choose
   **Blacksburg Prayer Walk (rebuild)**.

That fifth step is the one that matters. There are two configurations in this
repository: the original build, and this one. The default is the original.

6. Click **Create codespace**.

A tab opens that looks like a code editor. You can ignore all of it.

## 2. Wait

It is setting itself up, and it says which of five steps it is on. The longest is
installing the app's dependencies.

When it finishes you will see:

```
==> Prayer Walk is starting on port 8000
```

## 3. Get the address

1. Click the **PORTS** tab in the panel at the bottom.
2. Find the row for port **8000**.
3. Right-click it, choose **Port Visibility**, then **Public**.

That last step is required. Without it, your phone gets a login page instead of
the app, because your phone is not signed in to this Codespace.

4. Hover the **Forwarded Address** and click the copy icon.

## 4. Open it on your phone

Send yourself the address however you like and open it. You should see the town
percentage, a dark map of Blacksburg, and a loop already drawn with one button
under it.

**Add it to your home screen** to see it as a real app, without the browser bars:

- **iPhone:** Share button, then *Add to Home Screen*
- **Android:** the three-dot menu, then *Install app* or *Add to Home screen*

## 5. Walk

Tap **Start walking** and walk. Streets tick off as you pass them. When you are
back, tap **Finish walk**, take off anything you did not actually walk, and tap
**Add these streets to the map**.

Nothing reaches the shared map until that last tap.

---

## Worth knowing while you try it

**Your location never leaves the phone during a walk.** Street matching runs on
the device against the map it already downloaded. The only time a location is
sent anywhere is if you tap *Check my track for streets I missed*, and the
server keeps none of it.

**It works with location switched off.** You pick streets by hand, as stretches
named by their corners. Try it: it is a real path, not a fallback.

**It works with no signal.** Finish a walk in aeroplane mode and it saves to the
phone and goes up when you have signal again. It can only land once, however
many times it retries.

**The percentage is provisional.** The street network is about 9.5% too big,
because the build could not reach the Town's GIS and had to derive streets from a
map archive that cannot tell a public street from an apartment drive. Some
streets on the map should not be walked. See
[`data-provenance.md`](data-provenance.md).

**There is no home count.** No address data was reachable, so rather than show a
number nobody can stand behind, the app shows nothing there.

## If something looks wrong

**A login page instead of the app.** Port 8000 is still private. Go back to
step 3.

**A blank or grey map.** Give it a moment on first load: the map archive is
4.4 MB and is fetched in pieces. It is not cached for offline use, so the very
first launch needs signal.

**"Route planning is not running yet."** The database or the network build did
not finish. In the Codespace terminal:

```bash
python3 rebuild/data/pipeline/extract_network.py
python3 rebuild/db/load_network.py
```

**Everything stopped.** Close the Codespace tab and reopen it from the GitHub
Codespaces page. It restarts on its own.
