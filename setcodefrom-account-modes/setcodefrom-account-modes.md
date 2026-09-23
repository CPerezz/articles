# What your account can become after SETCODEFROM

*Four things people keep asking for, a few they will ask next, and which EIP opens each door.*

[SETCODEFROM](https://eips.ethereum.org/EIPS/eip-8298) is one instruction with a small job: point your account's code hash at another contract's already deployed code. It only ever touches the account running it, it never installs empty code or a delegation indicator, and the fee is flat no matter how big the code you're adopting is. That's the whole opcode.

What it opens up is bigger than the opcode. Once your account can pick up real code on demand, "what kind of account do I want to be" becomes an actual menu. So here's the menu, mostly in pictures:

1. Move to a code account, but keep signing with my own ECDSA key
2. Cheaply deploy a contract whose bytecode is identical to one already deployed
3. Retire the ECDSA key for good
4. Come back to ECDSA from a code account

A few of these lean on EIPs that are still drafts. I'll flag those as they show up. 7702 and 3607 are already live.

## The shapes and the line

![Figure 1: the map with EIP-7851 included, EOA, a 7702 delegate with the key on, a delegate with the key off, and regular code, with every move between them. The dashed red line is the point past which only code decides, and nothing crosses back over it.](figures/f1-map-with-7851.svg)

Left of the line, your key is always the one steering: it can delegate, redelegate, or clear itself back to a plain EOA whenever it wants. Cross the line and steering changes hands to whatever code you adopted. That's not a bug, it's the entire point of retiring a key.

[EIP-7851](https://eips.ethereum.org/EIPS/eip-7851) (draft) is the third box: a delegate that switches its own key off with `SETSELFDELEGATE`. Look at where it lands though. No plain transactions, no redelegation, no `ecrecover`, and a wallet that only code can change. That's exactly what a code account gives you, and SETCODEFROM gets you there in the same single move, swaps the wallet later just as easily, and doesn't add a second indicator format (`0xef0101`) that other EIPs like 8141 don't even mention yet. So it doesn't really buy us anything. We should probably skip it, and just aim to ship the best version of SETCODEFROM possible. Without it, the map gets simpler:

![Figure 2: the same map without SETSELFDELEGATE. Three shapes, one crossing, and the two rules that stop anything from coming back.](figures/f1-map.svg)

A few things this map says on purpose:

- SETCODEFROM is self only. It can never reach out and change somebody else's account.
- The arrow back from CODE is red because the specs block it, not because I left it off. 8298 only accepts a source whose code hash isn't the empty one and whose code doesn't start with `0xEF`, so SETCODEFROM can't copy "no code" or a 7702 indicator onto you. 7702 skips any authorization from an account that already has real code (its authority must be "empty or already delegated"). And `SELFDESTRUCT` only deletes a contract created in the same transaction ([EIP-6780](https://eips.ethereum.org/EIPS/eip-6780)), which a migrated account never is. Nothing else writes an account's code.
- Why that's a feature: 8298 says ECDSA transaction origination "remains permanently disabled" after a migration. If code could turn itself back into a key account, a retired, leaked or quantum broken key would get the account back, and for a fresh contract so would anyone who found a colliding key. Code can still adopt a new implementation as often as it likes. It just stays code.
- A 7702 authorization to `0x0` is not a delegation to address zero. 7702 treats it as "clear": the code hash goes back to empty, no indicator is left behind, and the account is a plain EOA again, byte for byte (geth does exactly this). Your key sends normal transactions, `ecrecover` works, and 8141 gives you the protocol's default code. No contract runs, no Solidity is involved. Only your key can make this move, and only from a delegate with the key on.

## Who can do what

![Figure 3: a grid of the four shapes against four channels, sending a plain transaction, signing a 7702 authorization, being recovered by ecrecover, and sending an 8141 frame transaction, with which EIP closes or opens each cell.](figures/f2-who-can-do-what.svg)

Three separate rules close the door on your key, one at a time, and none of them talk to each other: [EIP-3607](https://eips.ethereum.org/EIPS/eip-3607) blocks plain transactions from any address with real code, the [EIP-7702](https://eips.ethereum.org/EIPS/eip-7702) authorization check blocks redelegating an address that already has real code, and [EIP-8151](https://eips.ethereum.org/EIPS/eip-8151) (draft) blocks `ecrecover` from ever returning that address again. Add them up and a key behind real code has nothing left on this chain.

Why not let each account choose whether `ecrecover` still works? Because the contracts it matters for can't ask your account anything. An [ERC-2612](https://ercs.ethereum.org/ERCS/erc-2612) `permit` just runs `ecrecover` on a bare `v, r, s`. If that kept working after you moved to code, your old key could still sign away your tokens there, skipping your wallet's rules, and forever if the key leaks or gets broken. Contracts that ask your account through ERC 1271 keep working, and there your wallet decides.

If you want plain `ecrecover` apps to keep trusting your key, stay a delegate with the key on. The choice is the shape.

## Want 1: a code account that still runs on your ECDSA key

![Figure 4: keeping your ECDSA key. Stay a delegate and the key can walk around your wallet's rules, or cross with SETCODEFROM and the key only gets in through a frame transaction, where the protocol checks its signature natively and your code decides.](figures/f3-keep-the-key.svg)

**Stay a delegate.** Your key keeps everything: plain transactions, switching or clearing the delegation, and `permit` through `ecrecover`. Fully reversible. The catch: your wallet's rules are only advice, since the key can walk around them, and your wallet code can move you across the line without your key, so pick it like you'd pick a key.

**Cross with SETCODEFROM.** Adopt a wallet template that approves [8141 frame transactions](https://eips.ethereum.org/EIPS/eip-8141) signed by your key. The protocol verifies that signature natively before any code runs, the same way it checks a normal transaction signature. Your code only reads who signed (`SIGPARAM`) and applies its rules. No Solidity ECDSA, no precompile call. And since the key has no side door left, those rules actually bind.

This doesn't undo SETCODEFROM. The key has no power of its own anymore: your code chooses to trust it, the same way it could trust a passkey, and a template that stops accepting it retires it.

What you give up: plain transactions, and contracts that only run `ecrecover` (8151). Contracts that ask your account through ERC 1271 still work, but there your code checks the signature itself and `ecrecover` won't return your own address. Use the [ECMUL trick](https://ethereum-magicians.org/t/eip-8151-account-code-restricted-ecrecover/27690) (one `ecrecover` plus a `MODEXP` or two) or a second owner key whose address has no code.

## Want 2: a cheap way to deploy a contract whose bytecode is identical to one already deployed

This is the other half of what SETCODEFROM is for. The new account just points at code that's already stored instead of paying to store it again, and since it never had a key, nothing is left dangling that someone has to remember to switch off.

![Figure 5: a new contract's initcode writes its per instance state and adopts an existing template's code with SETCODEFROM, for a flat fee instead of paying code deposit per byte, contrasted with a 7702 wallet that always carries a live key by design.](figures/f4-no-key-contract.svg)

Under [EIP-8037](https://eips.ethereum.org/EIPS/eip-8037) every byte of new code costs 1530 gas, so a 32 KiB contract pays about 50.1M gas in code deposit, even when the exact same bytes are already on chain. With SETCODEFROM, the new contract's initcode writes its per instance state and adopts the template's code for a flat 9300 gas warm or 12200 cold, whatever its size. Nothing gets deposited. You still pay for the new account itself, like any deployment, because that part really is new state.

No key ever existed at that address, so even a `2^80` collision key gets nothing: 3607, the 7702 authority check and 8151 shut it out like any real key.

## Want 3: retire the key for good

What you want here: move to a code wallet that doesn't rely on a 7702 delegation or on your ECDSA key anymore. It's the migration 8298 was written for, for example onto a post quantum key.

![Figure 6: one type 4 transaction that delegates to a migrator, stores the post quantum wallet state and adopts a shared template, closing plain transactions, redelegation and ecrecover at once.](figures/f5-retire-the-key.svg)

An EOA has no code, so it can't run SETCODEFROM by itself. 7702 gets it there: one type 4 transaction delegates you to a migrator, calls yourself so the migrator runs in your account, stores your post quantum key and recovery config, and adopts a PQ wallet template. All three doors close at once, and the new code doesn't trust the old key.

Gate the migrator. A 7702 delegation stays in place even if the rest of the transaction reverts, so after a failed migration you're left delegated to the migrator with your key still on. If anyone can call it, anyone can install their own key. Only let it run on a call from yourself or your own signature, and if it fails, sign a fresh authorization to leave.

This retires the key on this chain only. It still signs on other chains where your address has no code, off chain, and in contracts that check ECDSA in their own code. And if you think the key leaked, the same move works as a panic button, as long as your transaction lands before the attacker's.

## Want 4: back to ECDSA

![Figure 7: two ways back to ECDSA, a fresh 7702 authorization to zero from a live delegate, or SETCODEFROM adopting an ECDSA owner template from a code account, where your code has to check the signature in Solidity. Legacy transactions and third party ecrecover stay shut either way.](figures/f6-back-to-ecdsa.svg)

Two different starting points, two different answers. If you're still a plain 7702 delegate with the key on, a fresh authorization to `0x0` clears you straight back to a true EOA, no different from one that never delegated.

If you're already a code account, there's no clearing your way out. You can adopt an "ECDSA owner" template with `SETCODEFROM` so your code trusts your key again, but then your code has to check the signature itself, and `ecrecover` won't return your own address anymore (8151). So the check runs in Solidity, or through the ECMUL trick from Want 1, and either way it costs more gas and runs slower than a native check. If ECDSA is all you want, it's not worth it: a 7702 delegation already gives you native ECDSA. Native checks through 8141 frame transactions could close that gap, and we leave that open to explore.

What stays shut, deliberately: plain legacy transactions (3607) and any third party contract trusting that address through naive `ecrecover` (8151). Nothing about 3607 was actually reversed, since what came back is your code choosing to trust a signature, exactly the way it could choose to trust a passkey or a post quantum scheme instead.

This same "adopt a new template, same address, same storage, no proxy" trick is also just how you upgrade in place at any point along the way: ECDSA today, a passkey tomorrow through 8141's `P256` scheme or the [secp256r1 precompile](https://eips.ethereum.org/EIPS/eip-7951) directly, a post quantum scheme after that through an `ARBITRARY` signature entry. Proxies can graduate into this too, since delegated execution is allowed to adopt code for its caller, but once you do, the proxy's old upgrade slot is dead weight: graduate only into code whose own upgrade path is `SETCODEFROM` from here on.

## Cheat sheet

![Figure 8: a table mapping eight things you might want, EOA perks, a reversible smart wallet, a code account that still trusts your key, a cheap copy of a deployed contract, retiring the key, switching wallets, going back to a plain EOA, and an ECDSA owner again after leaving ECDSA, to the exact move and the EIPs it needs.](figures/f7-cheat-sheet.svg)

**Verdict:** only two things are actually irreversible on this chain, protocol level ECDSA authority and blind `ecrecover` trust, and both are irreversible by design, not by accident. Everything else on this page, including coming back, is a move your own code or your own key can make, and every single one has an EIP number sitting right next to it.
