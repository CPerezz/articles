# Pay like a card, settle like Ethereum

*Card-terminal UX for payments from any rollup, with no bridge, no middleman and no one new to trust. That's what stacking FCR and EEZ unlocks: about two slots today, a card tap as Ethereum's slots shrink.*

![](figures/hero.jpeg)

You hold ETH on a rollup. The shop wants USDC and only watches Ethereum's base layer. It has never heard of your rollup, and it won't integrate yours or the next one. Multiply that by every rollup and every shop and you get the fragmentation everyone complains about: liquidity stuck on islands, each with its own bridge you have to trust and its own wait.

Two pieces of Ethereum infrastructure fix it together. [FCR](https://github.com/ethereum/consensus-specs/blob/master/specs/phase0/fast-confirmation.md) (the **Fast Confirmation Rule**) shrinks the wait before a landed block can be trusted. [EEZ](https://github.com/eez-association/eez-core-protocol) (the **Ethereum Economic Zone**) removes the separate crossing between your rollup and the base layer. They fix two different waits, so only stacked does the shop ship in seconds instead of minutes or days.

## The two waits

![Figure 1: the two waits. Getting there: your value crosses from your rollup to the base layer through a trusted bridge or market maker, or the rollup's own trustless exit, which can take up to about a week. Being believed: once it lands in a block, more blocks pile on and confidence builds until a reorg can't undo it, about 13 minutes. EEZ fixes the first wait and removes the trusted step with it; FCR fixes the second.](figures/f1-two-waits.svg)

Any cross-layer payment has two separate waits stacked on top of each other, and they get fixed by two separate things:

- **Getting there**: your value has to actually leave the rollup and arrive where the shop can see it. Today that means trusting a bridge or a market maker to front the funds, or waiting out the rollup's own exit, up to about a week.
- **Being believed**: once something lands on the base layer, the shop has to be confident it's staying there before handing over the goods — a block can still be reorged for a while after it's included.

## Build it the way checkout works today

![Figure 2: today's checkout. Your ETH leaves the rollup through a trusted bridge or market maker (minutes; the rollup's own trustless exit takes up to about a week), lands on the base layer, and only then does the shop start its own ~13 minute wait for finality before shipping.](figures/f2-today.svg)

Without either fix, the shop integrates your rollup specifically, or it doesn't take your money. If it does, your ETH first has to get there: either you trust a market maker to front USDC against a promise of your ETH (fast, but now you're trusting someone), or you use the rollup's own canonical exit, which can take anywhere from a few minutes to about a week depending on how that rollup proves its state. Only once the money has actually arrived does the shop start its *own* clock — about 13 minutes for Ethereum's base layer to make that arrival practically irreversible. Repeat the integration work for every rollup you want to accept from.

## Fix 1: FCR shrinks the "being believed" wait

![Figure 3: your block lands and validators' votes (attestations) pour in during the slot; once enough have arrived, FCR marks it safe, Ethereum's "safe" tag, about 13 seconds after it landed. Below, the 64 slots full finality takes, about 13 minutes, and the lock at the end of them. Two chips note FCR's conditions: votes arrive on time, and no more than 25% of stake acts adversarially.](figures/f3-fcr.svg)

Think of a card payment at a physical checkout: "approved" flashes in a second or two and the clerk hands you the bag. It's provisional, resting on the card network's word, and in rare fraud cases it can still be clawed back; the irreversible settlement between the banks comes later. [FCR](https://github.com/ethereum/consensus-specs/blob/master/specs/phase0/fast-confirmation.md), merged into Ethereum's consensus specs on 2026-04-16, is that "approved" screen for a block:

- **Fast**: once enough validators have attested to a block, about one slot (~13 seconds) after it lands, a node can mark it `safe` and act on it, instead of waiting ~13 minutes for full, slashing-backed finality.
- **Conditional**: it assumes attestations arrive on time and no more than 25% of stake acts adversarially. Break those and, unlike finality, nobody gets slashed; the rule just falls back to waiting for finality.
- **No fork needed**: it's a client-side rule, not a network upgrade. Some consensus clients ship it today, others are still in release candidates.

## Fix 2: EEZ removes the "getting there" wait

![Figure 4: today, your money sits in limbo between two separate ledgers, with a bridge you have to trust in the middle. With EEZ there's no bridge and nothing new to trust: the proof-and-update transaction and your checkout transaction are tied together inside one Ethereum block, so both land or neither does, and your rollup mirrors the result on the spot.](figures/f4-eez.svg)

The bridge model is a wire transfer: your ETH leaves your rollup's ledger, sits in transit, and lands on the base layer's ledger later, and if the transfer breaks halfway you can be stuck with nothing on either side. [EEZ](https://eez.io), a shared zone of rollups [built by Gnosis and ZisK with Ethereum Foundation co-funding](https://x.com/etheconomiczone/status/2038271122907578375), instead writes one receipt both ledgers sign off on together:

- **One block**: a builder packages your rollup action and the base-layer action into the same Ethereum block. Your rollup's contract only accepts the update once the base layer has recorded it in that block (the code calls this `postAndVerifyBatch`), and the rollup's own ledger mirrors it on the spot.
- **Nothing to trust in between**: no bridge operator or market maker ever holds your money mid-crossing. The base layer accepts your rollup's side only with a proof, so EEZ removes the trusted step, not just the wait. (Today's demo used a stand-in signer for that proof.)
- **All or nothing**: either the whole package lands or none of it does, so there's no half-sent state to get stuck in.
- **Composable**: by design the pieces can call each other and hand back results, so "swap on the base layer, then send the change back to your rollup" is one package, not three separate trips.

## Alike, different, and where they meet

![Figure 5: a side-by-side card. FCR fixes how long a landed block takes to trust; lives in every Ethereum consensus client; applies to any block, not just checkouts; rolling out client by client. EEZ fixes the crossing and removes the trusted bridge with it; lives in a specific set of rollup and base-layer contracts; applies only inside the zone; unaudited, early. Where they meet: EEZ's result is still just an ordinary Ethereum block — FCR can confirm it exactly as fast as any other.](figures/f5-alike-different.svg)

They don't compete, and they aren't the same feature wearing two names. FCR works on any Ethereum block, checkout or not, and lives in the consensus client every validator already runs. EEZ only works for actions between contracts inside its zone, and lives in a specific, still-unaudited set of rollup and base-layer contracts. They compose for one simple reason: EEZ's atomic package still lands as one ordinary Ethereum block, and FCR doesn't care what's inside a block to confirm it fast.

## Four ways to build your checkout

![Figure 6: a two-by-two grid, EEZ on one axis and FCR on the other. Neither: a trusted bridge plus full finality, minutes to about a week. FCR only: still the trusted bridge first, then ~13 seconds instead of ~13 minutes once it's landed — the bridge still dominates. EEZ only: one atomic block and no bridge, but the shop still waits ~13 minutes of finality to be safe. Both: one atomic block, confirmed in about two slots, roughly 25 seconds end to end.](figures/f6-four-builds.svg)

- **Neither.** Today's checkout: a bridge (minutes, trusted, or up to about a week, trustless) and then ~13 minutes of finality. The bridge usually dominates.
- **FCR only.** The bridge still has to run first, and you still have to trust it: FCR doesn't touch the crossing. Once the money has arrived, the shop's own wait drops from ~13 minutes to ~13 seconds. Still bridge-bound.
- **EEZ only.** The crossing disappears, and the bridge you had to trust goes with it: your rollup action and the base-layer action land as one package, one block. But the shop still has no fast-confirmation rule to lean on, so it waits the full ~13 minutes of finality to be sure that block is staying put.
- **Both.** One package, one block, confirmed in about two slots — the one it lands in, plus one more for FCR — roughly 25 seconds, assuming FCR's own conditions hold. This is the only quadrant that's fast, has no bridge to trust, *and* is a single integration.

## Both together: on the way to card speed

![Figure 7: the full flow. You sign one transaction. A builder packages your rollup's checkout action with the base-layer swap-and-pay action into the same block; your rollup's ledger mirrors it. The shop, watching only the base layer, sees the block land, sees it hit "safe" about one slot later, and ships — about two slots after you signed, with no bridge or middleman in between and no rollup-specific integration on its end.](figures/f7-end-to-end.svg)

You sign once. A builder puts your rollup's side (send ETH, get change back) and the base-layer side (swap into USDC, pay the invoice) in one Ethereum block. The shop never has to know your rollup exists: it watches the base layer, sees the block land, sees FCR mark it `safe` a slot later, and ships. Two slots, one integration, no bridge to trust. [The first atomic transaction of this kind](https://x.com/eduadiez/status/2107159200086319334) landed on mainnet on 2026-10-05: a much simpler transfer than this checkout, but built from the same pieces.

Twenty-five seconds still isn't a card tap. But **the whole checkout is counted in slots, not seconds**, so every cut to Ethereum's slot time cuts the wait with it:

![Figure 8: the same two-slot checkout at four slot times. 12-second slots (today): about 25 seconds. 6-second slots (EIP-7782, a draft): about 13. 4-second slots: about 9. 2-second slots, the speculative last step of the roadmap sketch: about 5 seconds, inside the band that feels like a card tap.](figures/f8-card-speed.svg)

[EIP-7782](https://eips.ethereum.org/EIPS/eip-7782), still a draft, proposes 6-second slots, and [Vitalik's roadmap sketch](https://x.com/VitalikButerin/status/2026779557479723418) keeps stepping them down, 12 → 8 → 6 → 4 → 3 → 2, with the last two steps still speculative. At 2-second slots the checkout takes about 5 seconds, close to the pause you already accept at a card terminal: you tap your phone, the shop sees `safe`, and the bag crosses the counter.

Only the stack rides that curve. Shorter slots don't shorten a bridge's exit window, and with today's finality the shop would still wait 64 slots, over two minutes even at 2-second slots. EEZ and FCR together turn the checkout into two slots, and two slots keep getting shorter.

## Cheat sheet

![Figure 9: a table — four ways to build the checkout, what each one needs, and the end-to-end time: neither (trusted bridge, 13 min to ~1 week), FCR only (trusted bridge, ~13 sec once landed), EEZ only (atomic block, no bridge, ~13 min), both (atomic block + FCR, no bridge, ~2 slots / ~25 sec).](figures/f9-cheat-sheet.svg)
