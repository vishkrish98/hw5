# Dashboard design — matching the desk tickets page

**Revision note:** this replaces an earlier dark-academia pass (near-black background, brass/moss
accents, Cormorant Garamond serif). The dashboard's look now matches `output/desk_tickets.html` —
the same cream/navy/gold palette, system sans-serif, pill badges, and card styling used throughout
the rest of this project's written output — so the live dashboard and the static planning/reflection
page read as one consistent product instead of two different visual languages. The structure below
(three columns, agent nameplates, ledger-styled feed, approval prompt) is unchanged from the prior
pass; only color and type changed.

## Palette and type, and why each color means something here

Every color in `src/index.css` is a `:root` variable, used nowhere as a raw hex outside that
file (two exceptions are the navy banner's own light-on-dark text colors, `#fdf6e6`/`#cdd7ea`,
which `desk_tickets.html`'s own banner hardcodes the same way rather than reusing the
light-surface text variable — a banner is a deliberately inverted context, not a content surface).
The variables: `--bg #f4f1e8` (warm cream, matching `desk_tickets.html` exactly), `--surface
#ffffff` (card background), `--elevated #faf2de` (a pale gold-tinted cream for selected states and
nested cards), `--hairline #e2ddcf`, `--text #2c2c2a`, `--muted #6b6a64`, `--navy #1b2a4a` (the
banner and "text on gold" color), `--accent` gold `#c9972e`, `--resolved` green `#3b6d11`,
`--approval` amber `#a3650c`, `--running` blue `#185fa5`, `--error` wine `#a13d3d`.

Gold is spent on the same three things it always was: the primary button, the balance figure, and
focus rings. The four status colors (green/amber/blue/wine) are the only other color in the app,
and mean one thing each everywhere — green is always "resolved," amber is always "needs a human,"
blue is always "running right now," wine is always "blocked or refused." A ticket chip, a decision
banner, and the approval card border all reuse the same four colors for the same four meanings.

Typography is a single system sans-serif stack (`-apple-system, "Segoe UI", Helvetica, Arial,
sans-serif`) everywhere, headlines included — the same stack `desk_tickets.html` uses, dropping the
earlier serif/sans split entirely. Ticket numbers and section labels ("Tickets," "The desk," "The
ledger") still render in small caps; every dollar figure still uses tabular numerals so a column of
them lines up.

## Layout: three columns, because this is three different jobs

Unchanged from the prior pass:
- **Tickets** (left, 280px, sticky) — a catalogue index card per ticket: its number, subject,
  type, requester, and status chip.
- **The desk** (center, flexible, the largest column) — everything about *this one ticket*: its
  meta, the run button, the per-agent summary, the five agent nameplates, and the full
  ledger-book feed underneath.
- **The ledger** (right, 300px, sticky) — money, full stop. The balance in large numerals, the
  starting/paid/current strip, and the approval prompt when one is waiting.

Below 990px these stack in that same order (tickets, desk, ledger) rather than reflowing into
something unrecognizable.

## The top bar, restyled as a banner

The sticky top bar is now a navy gradient banner with a gold bottom border — the same visual
signature as `desk_tickets.html`'s page banner, just compressed into a sticky 64px bar instead of a
full-width hero block. The brand mark and tagline use the banner's own light cream/ice-blue text
colors (not the content-surface `--text`/`--muted` variables), since the banner is a dark surface
sitting above an otherwise entirely light app — matching exactly how `desk_tickets.html` treats its
own banner as a separate color context from its cards. The cash pill sits on the banner as a
near-white rounded badge with navy text (gold-on-navy would repeat the banner's own border color
and wash out; navy-on-near-white is the same high-contrast pairing used for gold buttons elsewhere
in the app).

## How the five agents read differently

Unchanged in behavior, re-colored for the new palette. Each agent is a nameplate tile: a line icon,
its name, a one-line role, and a live status derived entirely from this ticket's own event history
(`src/agentStatus.ts`) — idle, thinking, calling tool, done, or blocked, exactly as before. Each
agent now carries one of the app's five non-status identity colors instead of the old brass/moss/
amber/mauve set: **Boss** navy (echoing the banner — the final-call agent), **Inventory** teal,
**Accounting** green (ties naturally to money), **Facilities** amber, **Customer Service** purple.
These are drawn from the same family as the status colors but are a distinct, agent-only palette —
nothing else in the app uses teal or purple, so those two colors always mean "this is Inventory" /
"this is Customer Service" at a glance.

Customer Service's draft still gets special treatment everywhere it appears: rendered as an actual
letter — to/subject/body — with a one-click Copy button.

## The ledger-book (activity feed)

Unchanged: a ruled row per entry (step number, agent name in its tint, the action, a timestamp),
auto-scrolling to the newest line, hairline rules between entries. Tool calls and their results
render as small monospace pills; an agent's actual conclusion renders as a plain sentence; a
pulsing "entry pending…" row sits at the bottom while a run is in progress.

## The ledger (balance) and approvals

Unchanged in mechanics, re-colored: the checking balance sits in both the banner pill and the large
right-column figure, both still flash gold and the banner dot still flips green→wine the instant
the balance changes — only then, nothing animates without a real change behind it. The approval
prompt still shows payee/amount/reason derived client-side from `src/approvalContext.ts` (no
dedicated backend field for either), Approve still executes the real payment and locks into a
confirmation state, and Decline is still a local-only dismissal with no backend route.

## Resolved tickets

Unchanged: a ticket at `status: resolved` gets a rotated, bordered "RESOLVED" stamp — now green
instead of moss, matching the new `--resolved` variable — sitting above the ticket's own heading.

## What a full walk-through actually showed (unchanged from the original pass)

Running ticket 102 (the rent notice) end to end: Facilities read lease 1 ($2,400, due in 2 days),
Accounting confirmed the balance covered it, Boss set the ticket to "needs approval," and the
approval card correctly pulled "Elm City Properties" and "$2,400.00" out of the already-logged tool
results with no hand-wiring per ticket. Approving it dropped the balance live in both the banner
pill and the ledger figure, added a "Paid lease #1 −$2,400.00" line to the strip, and locked the
approval card into its confirmed state. Nothing here needed a new backend field, and nothing about
this behavior changed when the palette did — this walk-through is about the mechanics, which this
restyle deliberately left untouched.
