# Try it on your phone

No software to install. You'll click a few buttons on the GitHub website, wait, and
get a link to open on your phone.

**About 10 minutes**, most of it waiting.

---

## Before you start

You need a GitHub account, signed in, with access to this repository. That's it.

One thing worth knowing up front: this creates a **temporary computer** that GitHub
runs for you. It's free within a monthly allowance you're very unlikely to reach just
trying this out. It goes to sleep when you stop using it, and you can delete it when
you're done. It is **not** where the real pilot should live — that's a separate,
permanent setup.

---

## Step 1 — Start the computer

1. Go to the repository page on GitHub.
2. Make sure the branch selector near the top-left says
   **`claude/blacksburg-prayer-walk-pwa-djiq0l`**. If it says something else, click it
   and choose that one.
3. Click the green **`< > Code`** button.
4. Click the **Codespaces** tab in the little panel that opens.
5. Click **Create codespace on claude/blacksburg-prayer-walk-pwa-djiq0l**.

A new browser tab opens with something that looks like a code editor. That's normal.
You don't have to understand any of it.

## Step 2 — Wait

It's now setting itself up. You'll see text scrolling in a panel at the bottom. It goes
through five steps, and it says which one it's on:

```
==> 1/5  Installing the Python parts
==> 2/5  Building the phone app
==> 3/5  Downloading Blacksburg's map data from the Town's servers
==> 4/5  Building the street network (this is the slow one, ~2 minutes)
==> 5/5  Setting up the database
==> Setup finished.
```

**This takes about five minutes.** Step 4 is genuinely slow — it's working out every
street, trail and campus path in Blacksburg and how they join up. If it looks frozen
there, it isn't.

When it finishes, it starts the app on its own and prints:

```
==> Open this on your phone:

    https://something-something-8000.app.github.dev
```

## Step 3 — Check it on the computer first

Copy that address and open it in a normal browser tab on your computer. You should see
the sign-up screen: **Blacksburg Prayer Walk**, with First name, Last name, Email.

Checking here first is worth the ten seconds. If something's wrong, it's much easier to
see on a big screen than on a phone.

**If you get a GitHub login page instead of the app**, the address isn't public yet:

1. In the editor, find the **PORTS** tab at the bottom (next to TERMINAL).
2. Find the row for port **8000**.
3. Right-click it → **Port Visibility** → **Public**.
4. Reload.

## Step 4 — Open it on your phone

Get the address onto your phone — text it to yourself, or email it. It's long; don't
try to type it.

Open it. Sign up with your name and email. You're in.

### Add it to your home screen

This is the part that makes it feel like a real app.

- **iPhone (Safari):** tap the **Share** button (square with an arrow), scroll down,
  tap **Add to Home Screen**.
- **Android (Chrome):** tap the **⋮** menu, tap **Add to Home screen** or **Install
  app**.

Now there's an icon on your home screen. Open it from there — no address bar, no
browser buttons, just the app.

---

## What to actually try

- **Generate a Prayer Walk**, then **Use my location**. Your phone will ask permission
  — that's expected, and it's asked once, only at this moment.
- **Slide between the five sizes.** Watch the distance, the time, the household count
  and the route on the map all change together.
- **Preview**, then **Start this walk.** Look at the turn-by-turn list.
- **Finish Walk** → **Review and edit**, and tap individual streets on the map to add
  or remove them. This is the fiddliest thing to do with a thumb — it's the bit I most
  want you to be rude about.
- Give it a **rating** at the end.
- Go back to the home screen and see the percentage move.

### One thing that will look like a bug and isn't

If you're **not in Blacksburg** when you tap "Use my location", you'll get:

> that start point is outside the Blacksburg area

That's correct — it's refusing to plan a walk somewhere it has no map for. To try it
from your sofa, use **"Choose a starting point on the map instead"** and tap anywhere
in town.

### If you want to see the administrator screens

Sign up in the app first, then in the editor's **TERMINAL** tab, paste this with your
own email:

```bash
sqlite3 bpw.db "UPDATE participants SET is_admin=1 WHERE email_normalized='you@example.com';"
```

Reload the app. An **Admin** tab appears, with the pilot summary and the connector
review.

---

## Stopping and starting again

- **To stop it:** click in the terminal panel and press `Ctrl` + `C`.
- **To start it again:** type `./go` and press Enter.
- **To come back another day:** GitHub → your profile menu → **Your codespaces** →
  click this one. It wakes up and restarts by itself. Setup does *not* run again.
- **To delete it:** same list, **⋯** → **Delete**. Nothing is lost that matters — the
  code is safe in the repository. You'd lose any test walks you recorded, which is
  fine.

## If something goes wrong

**The scrolling text stopped with red errors.** Read the last few lines. If it mentions
the Town's map servers, they were briefly unreachable — in the terminal, type
`bash .devcontainer/setup.sh` to try again.

**The app loads but "Generate a Prayer Walk" fails.** The map data probably didn't
download. Same fix as above.

**The link works on the computer but not the phone.** Almost always the port-visibility
thing in Step 3.

**Anything else:** copy the last twenty or so lines of the terminal and send them to me.
That's usually enough to say exactly what happened.

---

## When you've seen enough

If it's worth putting in front of people, the next step is a permanent home so everyone
gets a link that always works — that's [`docs/15-pilot-deployment.md`](15-pilot-deployment.md),
which is written for whoever sets it up rather than for you.
