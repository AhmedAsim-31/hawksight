# Model benchmark

How the default model was chosen.
Every model reviewed the same pull request on a MacBook Pro M3 Pro with 18 GB of memory, through the same context builder hawksight uses, at temperature 0.2.

## The test pull request

Three small server files with five planted bugs:

- `payments.py`: SQL injection in a lookup query (P0), a hardcoded live-looking Stripe secret key (P0), and a check-then-act race in a balance withdrawal (P1).
- `notify.ts`: an off-by-one loop bound (`i <= length`), and an async `send()` called without `await`.
- `format.py`: clean, so any finding there is a false positive.

A re-review round followed: a seeded earlier review plus author replies.
A good model keeps the SQL injection finding (weak rebuttal), drops the two findings with valid rebuttals, and answers each reply.

## Results

| Model | Runtime | Bugs caught | Re-review | Review time | Generation | Memory | Worst UI stutter |
|---|---|---|---|---|---|---|---|
| **MiMo-V2.6 Distill 9B Q4_K_M** | Ollama | **4/5** (missed `await`) | pass | 128 s | 20 tok/s | 6.1 GB | 15 ms |
| Mellum2.1 12B-A2.5B MXFP4 (MoE) | Ollama | 3/5 (missed race, `await`) | kept a rebutted finding | **87 s** | **45 tok/s** | 7.0 GB | 24 ms |
| Qwen3.5 9B 4-bit | mlx-lm | 3/5 (missed race, `await`) | kept SQLi, two false positives | 109 s | 23 tok/s | 8.2 GB | 578 ms |
| Qwen3.5 9B Q4_K_M | Ollama | 2/5, plus a false SQL injection | rated the secret P2 | 290 s | 24 tok/s | 7.6 GB, heavy swap | 22 ms |
| qwen2.5-coder 7B | Ollama | 1/5 (off-by-one only) | parroted the replies | 78 s | 23 tok/s | 5.6 GB | 16 ms |

qwen2.5-coder 14B was dropped early: it pushed an 18 GB Mac to critical memory pressure.
mlx-lm prefilled about 4x faster than Ollama but caused visible system hitches (430 to 580 ms), and leaked its reasoning into the review text.

## Verification pass

With the verification pass on, the same pull request (after the SQL injection and off-by-one were fixed) produced 7 raw findings.
Verification kept the 2 real ones (the committed key and the withdrawal race) and dropped 5: a duplicate, an already-fixed SQL claim, and three non-bugs.
Each check took 4 to 5 s, because the check reuses the review prompt's KV cache.

## Takeaways

- MiMo 9B is the default: best catch rate, clean re-reviews, no stutter. Pick Mellum if review speed matters more than catching races.
- No model caught the missing `await`.
- One fixture is a strong signal, not proof. Larger models (Qwen3.6-35B-A3B, Devstral Small 2) need more than 18 GB of memory.
