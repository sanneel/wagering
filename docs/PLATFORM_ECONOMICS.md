# Economics & retention

How the platform makes money, whether an 8% withdrawal fee can fund bonuses, and
a concrete retention plan. Numbers are a model to reason with, not a forecast —
the two big unknowns (Payed.co's real fees and player churn) are called out.

---

## 1. Where money comes from

Two levers exist in the code today:

- **Withdrawal fee on profit** (`WITHDRAWAL_FEE_PERCENT`, default 20%). Charged
  only on the part of a withdrawal above what the player deposited. Getting your
  own money back is free.
- **Match / tournament rake** (`RAKE_PERCENT`, `SPIN_RAKE_PERCENT`, both default
  **0**). A cut of every pot. Currently off — matches are 100% RTP.

The SpinCounter jackpot is **not** a revenue source and is no longer a cost
either: it's self-funded from a 15% skim of each entry pool with an EV-neutral
multiplier (Monte-Carlo: $1.68 paid vs $1.80 skimmed on a $12 pool). Before this
was fixed it paid ~$47.60 on a $12 pool — a catastrophic loss.

## 2. The model

Everything below is expressed as a percentage of **V = total deposits**.

```
margin%V  =  f·π   +   r·c    −   (d + w·W)
             fee     rake         payment processing
```

| symbol | meaning | base case |
|---|---|---|
| `f` | withdrawal fee on profit | (varied) |
| `π` | profit-withdrawn ÷ deposits — how much of the money transfers to winners and is cashed out | 0.40 |
| `r` | rake on every wager | (varied) |
| `c` | churn = handle ÷ deposits (times the average dollar is wagered) | 2.0 |
| `d` | Payed.co **deposit** fee | 2.0% |
| `w` | Payed.co **payout** fee | 1.0% |
| `W` | withdrawals ÷ deposits | 0.95 |

> **⚠️ Payed.co fees are assumptions.** I don't have their real card/crypto
> pricing — `d = 2.0%`, `w = 1.0%` are placeholders. Get a live quote and drop
> the real numbers in; they move every result below by their difference.

## 3. Can an 8% withdrawal fee fund bonuses? (the direct answer)

**On its own, no.** At the base case an 8% fee returns a **0.25% of deposits**
margin — it barely covers Payed.co, and it goes **negative** the moment churn/
skill is lower than assumed.

Margin as % of deposits:

| fee | rake | margin %V |
|----:|-----:|----------:|
| 8%  | 0%   | **0.25%** |
| 12% | 0%   | 1.85% |
| 15% | 0%   | 3.05% |
| 20% | 0%   | 5.05% |
| 8%  | 5%   | **10.25%** |
| 8%  | 10%  | 20.25% |
| 0%  | 10%  | 17.05% |

The 8%-fee-only line is dangerously churn-sensitive:

| churn/skill `π` | margin %V at 8% fee |
|---|---|
| 0.25 (casual) | **−0.95%** (loss) |
| 0.40 (base)   | 0.25% |
| 0.60 (sharks) | 1.85% |

**Why:** the fee is charged only on *profit*, which is a fraction of volume,
while Payed.co charges on *gross* deposit and withdrawal volume. A profit-only
fee of 8% is simply too thin to clear ~3% of gross processing.

## 4. The fix: a modest rake is the real engine

A rake is charged on **every** wager, so it's a reliable hold that doesn't
depend on who wins. It's also how comparable skill-gaming platforms actually
earn (entry-fee cuts of 10–20% are typical). Adding just **5%** transforms the
picture:

| structure | margin %V | bonus budget (40% reinvest) | per $50 deposit |
|---|---|---|---|
| 8% fee only | 0.25% | 0.10% | **$0.05** |
| 8% fee + 5% rake | 10.25% | 4.10% | **$2.05** |
| 8% fee + 10% rake | 20.25% | 8.10% | **$4.05** |

**Recommendation.** Make a **5–8% entry rake the primary revenue** and keep the
withdrawal fee low and player-friendly (8%, or even 0% as a marketing hook —
"cash out free"). The code already supports this: set `RAKE_PERCENT` /
`SPIN_RAKE_PERCENT`. A 100%-RTP promise plus a thin profit fee looks generous
but cannot fund a business or its bonuses.

## 5. How much for bonuses, then?

Reinvesting **40% of a positive margin** into acquisition + retention bonuses is
a healthy starting split (the other 60% covers fixed costs and profit).

- **8% fee + 5% rake → ~$2.05 of bonus budget per $50 deposited.**
- A bonus with an `Nx` rollover is *cheaper than face value*, because the player
  must wager it before cashing out and that wagering pays rake back. A $5 bonus
  at 1× rollover generates ~5% × $5 = $0.25 of rake, so its net cost is ~$4.75;
  higher rollover recovers more. This is exactly why every bonus in the code
  raises `rollover_requirement`.

A worked per-player example (deposit $50, churn 2.5×, 5% rake, 8% fee, base π):

```
rake revenue      5% × ($50 × 2.5)        = $6.25
fee revenue       8% × (0.40 × $50)       = $1.60
processing        2% × $50 + 1% × $47.50  = ($1.48)
──────────────────────────────────────────────────
gross margin/player                        ≈ $6.37
bonus budget (40%)                         ≈ $2.55
```

So a **$5 welcome bonus** (net cost ~$4.50 after its own rake) is affordable
**only if the player deposits/returns more than once** — i.e. bonuses must be
tied to behaviour that grows LTV, never given away flat.

## 6. Concrete bonus program (fits the budget)

Sized to the ~$2–2.5/player budget while using rollover to keep net cost down:

1. **Welcome match — 50% up to $10**, `Nx=3` rollover. New deposit of $20 →
   +$10 bonus locked until wagered 3×. Net cost ~$8 but only paid to players who
   actually deposit, and it drives first-session engagement (the moment a CS
   player feels "free money to play with").
2. **Daily reward** — a small login-streak credit ($0.25–$1, escalating over a
   7-day streak, `Nx=1`). Cheap, habit-forming, and self-limiting.
3. **Referral** — both sides get a bonus after the referee's first *settled*
   match (not first deposit — prevents self-referral farming). Paid from CAC,
   the cheapest acquisition channel in a friend-group game like CS.
4. **The SpinCounter jackpot** is already a free, self-funded excitement hook —
   lean on it in marketing, it costs the house ~nothing.

Guardrails so bonuses don't become a leak (this is also collusion defence — see
`PLATFORM_REVIEW.md` H4): all bonuses carry rollover; welcome/referral are
once-per-identity (device + payment instrument, not just account); referral pays
on a settled match, not signup.

## 7. Retention plan — think like the CS player

What makes a Counter-Strike player *stay*, mapped to what to build:

- **Fast to a match.** The single biggest retention lever is time-to-action.
  Land signed-in users straight on open tables, one-click join, pre-filled
  stakes. (Already close — keep it one tap.)
- **Progress they can see.** Profile with W/L, win-rate, net profit, biggest
  win, current streak; a visible rank/tier. CS players are stats-driven.
- **Something to chase.** The SpinCounter jackpot (free), weekly leaderboards
  with a prize pool, and seasons that reset ranks. Leaderboard standings are a
  strong return-trigger.
- **Social pull.** Rivalries (head-to-head record vs a specific player),
  party/friends play (already built), and referrals. CS is played in friend
  groups — lean into it.
- **Re-engagement.** Notifications/email: "your table filled", "your FACEIT
  match is ready", "you're 1 win off the weekly top 10", "your daily reward is
  waiting". This needs the notification system from the review (M6).
- **Trust = retention.** Fast, transparent payouts and provably-fair settlement
  (outcome comes from FACEIT) are themselves retention features in wagering —
  a player who cashes out smoothly once will come back.

Sequencing: profile/stats + daily reward + welcome bonus are the cheap,
high-impact first wave (partly shipped alongside this doc). Leaderboards/seasons
and notifications are the second wave and depend on the real-time/notification
work in the platform review.

## 8. TL;DR

- **8% withdrawal fee alone ≈ break-even and can't fund bonuses** (≈$0.05 per
  $50, negative if churn is low).
- **Add a 5–8% entry rake** as the primary, reliable revenue; then the withdrawal
  fee can stay low as a player-friendly hook.
- That yields **~10% margin of deposits → ~$2/$50 of bonus budget**, enough for a
  welcome + daily + referral program **if every bonus carries rollover** and is
  tied to real deposit/return behaviour.
- **Get Payed.co's real fees** — they swing every number here.
