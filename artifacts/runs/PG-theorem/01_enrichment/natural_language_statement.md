# Natural-Language Statement

Fix finite sets of states and actions, a parameter-independent transition kernel `P(s' | s, a)`, a parameterized policy `π_θ(a | s)` that is continuously differentiable in the parameter `θ`, a reward vector `r`, and an initial state-action distribution `p₀`.

From `P` and `π_θ`, form the state-action transition matrix `Π(θ)` whose entry from `(s,a)` to `(s',a')` is the probability of first moving to state `s'` under the environment and then choosing action `a'` under the policy. Assume the resulting dynamics are discounted or otherwise transient enough that `I - Π(θ)` is invertible for every parameter under consideration.

Define the state-action value vector `q(θ)` to be the expected total future reward from each state-action pair, define the visitation-frequency vector `d(θ)` to be the expected number of visits to each state-action pair, and define the total return `J(θ)` from the initial distribution. In matrix form these are `q(θ) = (I - Π(θ))⁻¹ r`, `d(θ) = p₀ (I - Π(θ))⁻¹`, and `J(θ) = d(θ) · r = p₀ · q(θ)`.

Then the derivative of the total return with respect to any parameter coordinate is obtained by placing the derivative of the transition matrix between the visitation frequencies and the value vector. In other words, for every coordinate `θ_i`, the partial derivative of `J` with respect to `θ_i` is `d(θ) (∂_i Π(θ)) q(θ)`.
