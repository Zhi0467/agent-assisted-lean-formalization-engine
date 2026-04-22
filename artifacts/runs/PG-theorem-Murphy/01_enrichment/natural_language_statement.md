Let `p0` be the initial row distribution on a finite state-action space, let `r` be the reward column vector, and let `Π(t)` be the transition matrix of the policy as a function of a real parameter `t`.

Assume that for all `t` sufficiently close to a base point `θ`, the following three series converge and define the occupancy vector `d(t)`, the value vector `q(t)`, and the total return `J(t)`:

- `d(t) = Σ_k p0 Π(t)^k`
- `q(t) = Σ_k Π(t)^k r`
- `J(t) = Σ_k p0 Π(t)^k r`

Assume also that `Π` and `d` are differentiable at `θ`.

Then `J` is differentiable at `θ`, and its derivative is given by the policy-gradient formula

`J'(θ) = d(θ) Π'(θ) q(θ)`.

Equivalently, in row/column notation,

`J'(θ) = dotProduct (d(θ) · Π'(θ)) (q(θ))`.
