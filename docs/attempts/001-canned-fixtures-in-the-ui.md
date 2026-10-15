# Attempt 001 — Canned fixtures as an offline fallback

**Opened.** During the UI build.
**Closed.** 2026-10-15, commit "remove canned fixtures on offline backend and make
extraction pipeline visible". Abandoned.

**Hypothesis.** The UI should not be blank when the backend is unreachable. Falling
back to a set of realistic clinical records makes the demo work offline, and a demo
that does not work is a demo that does not get shown.

**How we tested it.** Ran the frontend with no backend running. It rendered a
complete patient registry and a working ask screen, from `lib/fixtures.js`.

**What actually happened.** The UI was showing fake patient records and answering
questions about them, with no indication that any of it was fake.

For a clinical system this is the worst possible failure mode, and it is worth being
precise about why. The specific danger of a fixture fallback is not that someone
reviews the code and misses it — it is that **nothing about the screen is false**. The
records look like records, the answers look like answers, and the layout renders
identically whether the data is real or invented. The one signal that would
distinguish them was the one thing removed.

The same commit found the offline ask path doing the equivalent thing: returning
fixture answers for questions the backend never saw.

**Outcome.** Abandoned. `lib/fixtures.js` was stripped of its fake clinical records,
keeping only benchmark limitations — the one thing in it that was true. The fallback
path was deleted rather than changed:

> "Remove fallback-to-fixtures in `lib/api.js`; transport errors and unreachable
> backends now fail loudly with startup command"

The same commit made the extraction pipeline visible on the upload screen —
real stages, real elapsed time — so there is something true to look at instead.

**Why we moved on.** A loud failure is worth more than a convincing lie. The fix is
also better engineering: the fallback was masking every backend error during
development, so the UI looked finished while the API was being built underneath it.

### What this attempt is a reminder of

**A fixture fallback removes the signal that distinguishes demo from product.**

This is unusually dangerous in a domain where the output looks like domain output. In
a generic app, fixture data is recognisable as fixture data. A synthetic lab report
is indistinguishable from a real one to a reader who has not been told which it is.

The general form: if the fallback and the real thing render the same, the fallback is
not a fallback — it is an alternate source of unlabelled truth.

### The follow-up

A later commit, "honest offline status label, no phantom fallback claim", fixed the
status indicator that had been claiming a fallback that no longer existed. The
pattern is consistent: once the fixture path was gone, the label describing it
became its own small lie.

**What would change this decision.** Nothing. There is no scenario where showing
invented clinical records without saying so is the right behaviour.